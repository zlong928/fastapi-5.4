import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, Clock3, Eye, Loader2, Play, RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getPaper, getPaperExtractions, retryExtraction, runExtraction } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import {
  DEFAULT_EXTRACTION_QUERY,
  ExtractionStatusBadge,
  PaperStatusBadge,
  canExtractPaper,
  extractionStatusLabel,
  isExtractionBusy,
  shouldPollPaper
} from "@/pages/paperShared";

export function PaperExtractionTaskPage() {
  const paperId = Number(useParams().id);
  const [query, setQuery] = useState(DEFAULT_EXTRACTION_QUERY);
  const queryClient = useQueryClient();

  const paperQuery = useQuery({
    queryKey: ["paper", paperId],
    queryFn: () => getPaper(paperId),
    enabled: Number.isFinite(paperId),
    refetchInterval: (queryState) => shouldPollPaper(queryState.state.data) ? 2000 : false
  });
  const jobsQuery = useQuery({
    queryKey: ["paper-extractions", paperId],
    queryFn: () => getPaperExtractions(paperId),
    enabled: Number.isFinite(paperId),
    refetchInterval: (queryState) => (queryState.state.data ?? []).some((job) => isExtractionBusy(job.status)) ? 2000 : false
  });

  const runMutation = useMutation({
    mutationFn: () => runExtraction(paperId, query.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper", paperId] });
      queryClient.invalidateQueries({ queryKey: ["paper-extractions", paperId] });
    }
  });
  const retryMutation = useMutation({
    mutationFn: (jobId: number) => retryExtraction(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper", paperId] });
      queryClient.invalidateQueries({ queryKey: ["paper-extractions", paperId] });
    }
  });

  const paper = paperQuery.data;
  const jobs = jobsQuery.data ?? [];
  const currentJob = jobs[0] ?? paper?.latest_extraction_job ?? null;
  const isStarting = runMutation.isPending || retryMutation.isPending;
  const canStart = canExtractPaper(paper) && query.trim().length > 0 && !isStarting && !isExtractionBusy(currentJob?.status);

  if (paperQuery.isLoading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
        <Button asChild variant="ghost" size="sm" className="mb-3 rounded-xl px-2 text-slate-500">
          <Link to={`/papers/${paper.id}`}><ArrowLeft className="h-4 w-4" />论文详情</Link>
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <PaperStatusBadge status={paper.status} />
              {currentJob ? <ExtractionStatusBadge status={currentJob.status} /> : null}
            </div>
            <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight text-slate-950">{paper.title}</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" className="rounded-xl border-slate-200 shadow-none">
              <Link to={`/papers/${paper.id}/results${currentJob?.status === "done" ? `?job=${currentJob.id}` : ""}`}><Eye className="h-4 w-4" />提取结果</Link>
            </Button>
            <Button variant="outline" className="rounded-xl border-slate-200 shadow-none" onClick={() => { paperQuery.refetch(); jobsQuery.refetch(); }} disabled={paperQuery.isFetching || jobsQuery.isFetching}>
              {paperQuery.isFetching || jobsQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </Button>
          </div>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <BarChart3 className="h-4 w-4" />
            提取任务
          </div>
          {!canExtractPaper(paper) ? (
            <Alert className="mb-4 rounded-xl">
              <AlertDescription>当前论文还没有可提取的正文、图片或表格，请先完成解析。</AlertDescription>
            </Alert>
          ) : null}
          {runMutation.error ? (
            <Alert variant="destructive" className="mb-4 rounded-xl">
              <AlertDescription>{runMutation.error instanceof Error ? runMutation.error.message : "提取任务创建失败"}</AlertDescription>
            </Alert>
          ) : null}
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="min-h-36 w-full rounded-xl border border-slate-200 p-3 text-sm leading-6 outline-none transition focus:ring-2 focus:ring-slate-200"
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-slate-500">{query.trim().length}/2000</p>
            <Button type="button" className="rounded-xl" onClick={() => runMutation.mutate()} disabled={!canStart}>
              {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始提取
            </Button>
          </div>
        </section>

        <aside className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Clock3 className="h-4 w-4" />
            当前状态
          </div>
          {currentJob ? (
            <div className="space-y-3">
              <div className="rounded-xl bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <ExtractionStatusBadge status={currentJob.status} />
                  <span className="text-xs text-slate-400">#{currentJob.id}</span>
                </div>
                <p className="mt-3 line-clamp-3 text-sm leading-6 text-slate-700">{currentJob.query}</p>
                <p className="mt-2 text-xs text-slate-400">更新：{formatChinaDateTime(currentJob.updated_at)}</p>
              </div>
              {currentJob.status === "failed" && currentJob.error_message ? (
                <Alert variant="destructive" className="rounded-xl">
                  <AlertDescription>{currentJob.error_message}</AlertDescription>
                </Alert>
              ) : null}
              {currentJob.status === "failed" ? (
                <Button type="button" variant="outline" className="w-full rounded-xl border-slate-200 shadow-none" onClick={() => retryMutation.mutate(currentJob.id)} disabled={retryMutation.isPending}>
                  {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                  重试任务
                </Button>
              ) : null}
              {currentJob.status === "done" ? (
                <Button asChild className="w-full rounded-xl">
                  <Link to={`/papers/${paper.id}/results?job=${currentJob.id}`}>查看结果</Link>
                </Button>
              ) : null}
            </div>
          ) : (
            <div className="rounded-xl bg-slate-50 p-6 text-center text-sm text-slate-400">暂无提取任务</div>
          )}
        </aside>
      </div>

      <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-800">任务历史</h2>
        <div className="space-y-2">
          {jobs.map((job) => (
            <article key={job.id} className="flex flex-col gap-3 rounded-xl border border-slate-100 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <ExtractionStatusBadge status={job.status} />
                  <span className="text-xs text-slate-400">#{job.id} · {formatChinaDateTime(job.created_at)}</span>
                  <span className="text-xs text-slate-400">{job.result_count} 条结果</span>
                </div>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-700">{job.query}</p>
                {job.status === "failed" && job.error_message ? <p className="mt-1 line-clamp-2 text-xs text-red-600">{job.error_message}</p> : null}
              </div>
              <div className="flex shrink-0 gap-2">
                {job.status === "failed" ? (
                  <Button type="button" size="sm" variant="outline" className="rounded-xl border-slate-200 shadow-none" onClick={() => retryMutation.mutate(job.id)} disabled={retryMutation.isPending}>
                    <RotateCcw className="h-4 w-4" />重试
                  </Button>
                ) : null}
                {job.status === "done" ? (
                  <Button asChild size="sm" variant="outline" className="rounded-xl border-slate-200 shadow-none">
                    <Link to={`/papers/${paper.id}/results?job=${job.id}`}>结果</Link>
                  </Button>
                ) : (
                  <span className="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-400">{extractionStatusLabel(job.status)}</span>
                )}
              </div>
            </article>
          ))}
          {!jobsQuery.isLoading && !jobs.length ? <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-400">暂无任务历史</div> : null}
        </div>
      </section>
    </div>
  );
}
