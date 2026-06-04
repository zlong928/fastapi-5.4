import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, Download, Eye, FileText, Loader2, Play, RefreshCw, RotateCcw, Search, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { API_BASE_URL, batchRunExtraction, getExtractions, getPapers, getToken, retryExtraction } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { BatchExtractionResult, ExtractionJobListItem, PaperListItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DEFAULT_EXTRACTION_QUERY, EXTRACTION_PRESETS, ExtractionStatusBadge, canExtractPaperListItem, extractionStatusLabel, isExtractionBusy } from "@/pages/paperShared";

function progressTone(status: string) {
  if (status === "failed") return "bg-red-500";
  if (status === "done") return "bg-emerald-500";
  return "bg-blue-600";
}

function progressDetail(job: ExtractionJobListItem) {
  const progress = job.progress;
  if (!progress) return extractionStatusLabel(job.status);
  if (job.status === "done") return `完成 · ${job.result_count} 条结果 · 100%`;
  if (job.status === "failed") return `失败于 ${progress.phase_label} · 查看错误信息`;
  if (progress.phase === "VISUAL_ANALYSIS" && progress.figures_total > 0) {
    return `${progress.phase_label} · ${progress.figures_done}/${progress.figures_total} 张图完成 · ${progress.percent}%`;
  }
  return `${progress.phase_label} · ${progress.percent}%`;
}

function ExtractionProgressBar({ job }: { job: ExtractionJobListItem }) {
  const progress = job.progress;
  const percent = progress?.percent ?? (job.status === "done" ? 100 : 0);
  return (
    <div className="mt-3 space-y-1.5">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className={cn("min-w-0 truncate", job.status === "failed" ? "text-red-600" : "text-slate-500")}>{progressDetail(job)}</span>
        <span className="shrink-0 tabular-nums text-slate-400">{Math.round(percent)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn("h-full rounded-full transition-all duration-500", progressTone(job.status))}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      {progress?.message && job.status !== "done" ? <p className="line-clamp-1 text-xs text-slate-400">{progress.message}</p> : null}
    </div>
  );
}

function ExtractionJobCard({ job, onRetry, retrying, selected, onToggle }: { job: ExtractionJobListItem; onRetry: (jobId: number) => void; retrying: boolean; selected: boolean; onToggle: () => void }) {
  return (
    <article className={cn("rounded-md border bg-white p-4 transition", selected ? "border-slate-900 ring-2 ring-slate-900" : "border-slate-200")}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 flex-1 gap-3">
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              "mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded border transition",
              selected ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white hover:border-slate-400"
            )}
          >
            {selected ? <Check className="h-3.5 w-3.5" /> : null}
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <ExtractionStatusBadge status={job.status} />
              <span className="text-xs text-slate-400">#{job.id}</span>
              <span className="text-xs text-slate-400">{job.result_count} 条结果</span>
            </div>
            <Link to={`/papers/${job.paper_id}`} className="mt-3 inline-flex max-w-full items-center gap-2 text-base font-semibold text-slate-950 hover:text-slate-700">
              <FileText className="h-4 w-4 shrink-0 text-slate-400" />
              <span className="truncate">{job.paper_title}</span>
            </Link>
            <ExtractionProgressBar job={job} />
            <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-700">{job.query}</p>
            <p className="mt-2 text-xs text-slate-400">{formatChinaDateTime(job.created_at)} · {extractionStatusLabel(job.status)}</p>
            {job.error_message ? (
              <div className="mt-3 flex gap-2 rounded-md bg-red-50 p-3 text-xs leading-5 text-red-700">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span className="line-clamp-3">{job.error_message}</span>
              </div>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button asChild size="sm" variant="outline" className="rounded-md border-slate-200 shadow-none">
            <Link to={`/papers/${job.paper_id}/results?job=${job.id}`}><Eye className="h-4 w-4" />结果</Link>
          </Button>
          {job.status === "failed" ? (
            <Button type="button" size="sm" variant="outline" className="rounded-md border-slate-200 shadow-none" onClick={() => onRetry(job.id)} disabled={retrying}>
              {retrying ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              重试
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function PaperOption({ paper, selected, onToggle }: { paper: PaperListItem; selected: boolean; onToggle: () => void }) {
  const disabled = !canExtractPaperListItem(paper);
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      className={cn(
        "flex w-full items-start gap-3 rounded-md border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900",
        selected ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white hover:border-slate-300",
        disabled && "cursor-not-allowed opacity-50"
      )}
    >
      <span className={cn("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border", selected ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white")}>
        {selected ? <Check className="h-3.5 w-3.5" /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-sm font-medium text-slate-900">{paper.title}</span>
        <span className="mt-1 block text-xs text-slate-400">{paper.progress_label || paper.status}</span>
      </span>
    </button>
  );
}

export function ExtractionsPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState(DEFAULT_EXTRACTION_QUERY);
  const [activePreset, setActivePreset] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedJobIds, setSelectedJobIds] = useState<number[]>([]);

  const jobsQuery = useQuery({
    queryKey: ["extractions"],
    queryFn: getExtractions,
    refetchInterval: (queryState) => (queryState.state.data ?? []).some((job) => isExtractionBusy(job.status)) ? 2000 : false
  });
  const papersQuery = useQuery({ queryKey: ["papers", "extraction-picker"], queryFn: getPapers });

  const retryMutation = useMutation({
    mutationFn: (jobId: number) => retryExtraction(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["extractions"] });
    }
  });
  const [batchResults, setBatchResults] = useState<BatchExtractionResult[] | null>(null);
  const runMutation = useMutation({
    mutationFn: () => batchRunExtraction(selectedIds.slice(), query.trim()),
    onSuccess: (results) => {
      setBatchResults(results);
      queryClient.invalidateQueries({ queryKey: ["extractions"] });
      setSelectedIds([]);
    }
  });

  const jobs = jobsQuery.data ?? [];
  const papers = papersQuery.data ?? [];
  const filteredPapers = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return papers;
    return papers.filter((paper) => paper.title.toLowerCase().includes(q));
  }, [keyword, papers]);
  const canStart = selectedIds.length > 0 && query.trim().length > 0 && !runMutation.isPending;

  function togglePaper(paper: PaperListItem) {
    if (!canExtractPaperListItem(paper)) return;
    setSelectedIds((current) => current.includes(paper.id) ? current.filter((id) => id !== paper.id) : [...current, paper.id]);
  }

  function toggleJob(jobId: number) {
    setSelectedJobIds((current) => current.includes(jobId) ? current.filter((id) => id !== jobId) : [...current, jobId]);
  }

  function selectAllJobs() {
    setSelectedJobIds(jobs.map(job => job.id));
  }

  function clearJobSelection() {
    setSelectedJobIds([]);
  }

  function exportJobs(format: "csv" | "json" | "markdown") {
    if (selectedJobIds.length === 0) {
      alert("请先选择要导出的任务");
      return;
    }

    const token = getToken();

    if (selectedJobIds.length === 1) {
      // Single job export
      const jobId = selectedJobIds[0];
      const url = `${API_BASE_URL}/extractions/${jobId}/export?format=${format}`;

      fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      })
        .then(response => {
          if (!response.ok) throw new Error("导出失败");
          return response.blob();
        })
        .then(blob => {
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `extraction_${jobId}.${format}`;
          document.body.appendChild(a);
          a.click();
          window.URL.revokeObjectURL(url);
          document.body.removeChild(a);
        })
        .catch(error => {
          alert(error.message || "导出失败");
        });
    } else {
      // Batch export
      const params = new URLSearchParams();
      selectedJobIds.forEach(id => params.append("job_ids", String(id)));
      params.set("format", format);

      const url = `${API_BASE_URL}/extractions/batch-export?${params.toString()}`;

      fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      })
        .then(response => {
          if (!response.ok) throw new Error("导出失败");
          return response.blob();
        })
        .then(blob => {
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `batch_extraction_${selectedJobIds.length}_jobs.${format}`;
          document.body.appendChild(a);
          a.click();
          window.URL.revokeObjectURL(url);
          document.body.removeChild(a);
        })
        .catch(error => {
          alert(error.message || "导出失败");
        });
    }
  }

  return (
    <main className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-500">提取任务</p>
          <h1 className="mt-2 text-2xl font-semibold leading-tight tracking-tight text-slate-950">从论文证据中提取目标字段</h1>
        </div>
        <Button variant="outline" className="rounded-md border-slate-200 shadow-none" onClick={() => jobsQuery.refetch()} disabled={jobsQuery.isFetching}>
          {jobsQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </Button>
      </header>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-950">提取目标</h2>
          <div className="mt-3 mb-3">
            <div className="flex flex-wrap gap-1.5">
              {EXTRACTION_PRESETS.map((preset, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => { setActivePreset(i); setQuery(preset.query); }}
                  className={`rounded-md px-2.5 py-1.5 text-xs transition ${activePreset === i ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
          <textarea
            value={query}
            onChange={(event) => { setQuery(event.target.value); setActivePreset(-1); }}
            className="min-h-36 w-full rounded-md border border-slate-200 p-3 text-sm leading-6 outline-none transition focus:ring-2 focus:ring-slate-200"
            placeholder="描述你想从论文中提取的具体信息..."
          />
          {runMutation.error ? (
            <Alert variant="destructive" className="mt-3">
              <AlertDescription>{runMutation.error instanceof Error ? runMutation.error.message : "提取任务创建失败"}</AlertDescription>
            </Alert>
          ) : null}
          {batchResults ? (
            <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3">
              <p className="mb-2 text-xs font-medium text-slate-600">批量提取结果</p>
              <div className="space-y-1">
                {batchResults.map((item) => (
                  <div key={item.paper_id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="min-w-0 truncate text-slate-700">{item.paper_title || `#${item.paper_id}`}</span>
                    <span className={cn("shrink-0", item.status === "pending" ? "text-blue-600" : item.status === "skipped" ? "text-red-600" : "text-slate-500")}>
                      {item.status === "pending" ? "已创建" : item.error || item.status}
                    </span>
                  </div>
                ))}
              </div>
              <button type="button" onClick={() => setBatchResults(null)} className="mt-2 text-xs text-slate-400 hover:text-slate-600">关闭</button>
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Sparkles className="h-3.5 w-3.5 text-slate-400" />
              <p className="text-xs text-slate-400">已选择 {selectedIds.length} 篇 · {query.trim().length}/2000</p>
            </div>
            <Button type="button" className="rounded-md" onClick={() => runMutation.mutate()} disabled={!canStart}>
              {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始提取
            </Button>
          </div>
        </div>

        <aside className="rounded-md border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-950">选择论文</h2>
            <span className="text-xs text-slate-400">{papers.length} 篇</span>
          </div>
          <label className="relative block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索论文"
              className="h-10 w-full rounded-md border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none transition focus:ring-2 focus:ring-slate-200"
            />
          </label>
          <div className="mt-3 max-h-96 space-y-2 overflow-auto pr-1">
            {filteredPapers.map((paper) => <PaperOption key={paper.id} paper={paper} selected={selectedIds.includes(paper.id)} onToggle={() => togglePaper(paper)} />)}
            {papersQuery.isLoading ? <div className="rounded-md bg-slate-50 p-6 text-center text-sm text-slate-400">加载中</div> : null}
            {!papersQuery.isLoading && !filteredPapers.length ? <div className="rounded-md bg-slate-50 p-6 text-center text-sm text-slate-400">暂无可选论文</div> : null}
          </div>
        </aside>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-slate-950">任务历史</h2>
            {selectedJobIds.length > 0 ? (
              <span className="text-xs text-slate-500">已选择 {selectedJobIds.length} 个任务</span>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            {jobsQuery.isFetching ? <span className="inline-flex items-center gap-2 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />刷新中</span> : null}
            {jobs.length > 0 ? (
              <>
                {selectedJobIds.length > 0 ? (
                  <>
                    <Button type="button" variant="outline" size="sm" className="rounded-md border-slate-200 shadow-none" onClick={clearJobSelection}>
                      取消选择
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger>
                        <Button type="button" size="sm" className="rounded-md">
                          <Download className="h-4 w-4" />
                          导出 ({selectedJobIds.length})
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => exportJobs("csv")}>导出为 CSV</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => exportJobs("json")}>导出为 JSON</DropdownMenuItem>
                        {selectedJobIds.length === 1 ? (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={() => exportJobs("markdown")}>导出为 Markdown</DropdownMenuItem>
                          </>
                        ) : null}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </>
                ) : (
                  <Button type="button" variant="outline" size="sm" className="rounded-md border-slate-200 shadow-none" onClick={selectAllJobs}>
                    全选
                  </Button>
                )}
              </>
            ) : null}
          </div>
        </div>
        {jobs.map((job) => <ExtractionJobCard key={job.id} job={job} onRetry={(jobId) => retryMutation.mutate(jobId)} retrying={retryMutation.isPending} selected={selectedJobIds.includes(job.id)} onToggle={() => toggleJob(job.id)} />)}
        {jobsQuery.isLoading ? <div className="rounded-md bg-slate-50 p-10 text-center text-sm text-slate-400">加载中</div> : null}
        {!jobsQuery.isLoading && !jobs.length ? <div className="rounded-md bg-slate-50 p-10 text-center text-sm text-slate-400">暂无提取任务</div> : null}
      </section>
    </main>
  );
}
