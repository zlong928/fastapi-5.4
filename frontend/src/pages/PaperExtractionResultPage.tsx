import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, FileText, Image, Loader2, RefreshCw, RotateCw, Table2 } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getExtraction, getPaper, retryExtraction } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { ExtractionJob, ExtractionResult, PaperDetail, PaperFigure, PaperTable } from "@/lib/types";
import {
  ExtractionStatusBadge,
  SourceBadge,
  confidencePercent,
  fieldLabel,
  isExtractionBusy,
  resultMetricKeys,
  resultSourceCounts,
  resultsByMetric,
  shouldPollPaper,
  sourceLabel
} from "@/pages/paperShared";

function sourceIcon(sourceType: string) {
  if (sourceType === "figure") return <Image className="h-4 w-4" />;
  if (sourceType === "table") return <Table2 className="h-4 w-4" />;
  return <FileText className="h-4 w-4" />;
}

function lookupFigure(paper: PaperDetail, result: ExtractionResult): PaperFigure | undefined {
  return result.source_type === "figure" && result.source_id
    ? paper.figures.find((figure) => figure.id === result.source_id)
    : undefined;
}

function lookupTable(paper: PaperDetail, result: ExtractionResult): PaperTable | undefined {
  return result.source_type === "table" && result.source_id
    ? paper.tables.find((table) => table.id === result.source_id)
    : undefined;
}

function flattenContentValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(flattenContentValue).filter(Boolean).join("\n");
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, entry]) => {
        const flattened = flattenContentValue(entry);
        return flattened ? `${key}: ${flattened}` : "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return String(value);
}

function readableContent(content: string) {
  const trimmed = content.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return content;
  try {
    return flattenContentValue(JSON.parse(trimmed)) || content;
  } catch {
    return content;
  }
}

function DetailRow({ label, value }: { label: string; value?: string | number | null }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 break-words text-sm text-slate-800">{value}</dd>
    </div>
  );
}

function ResultSourceDetails({ result, paper }: { result: ExtractionResult; paper: PaperDetail }) {
  const figure = lookupFigure(paper, result);
  const table = lookupTable(paper, result);
  if (result.source_type === "figure") {
    return (
      <dl className="mb-3 grid gap-3 rounded-xl bg-slate-50 p-3 sm:grid-cols-3">
        <DetailRow label="figure_id" value={figure ? `${figure.figure_label} (#${figure.id})` : result.source_id ? `#${result.source_id}` : "-"} />
        <DetailRow label="caption" value={figure?.caption || readableContent(result.content)} />
        <DetailRow label="source" value={figure?.source || "figure"} />
      </dl>
    );
  }
  if (result.source_type === "table") {
    return (
      <dl className="mb-3 grid gap-3 rounded-xl bg-slate-50 p-3 sm:grid-cols-3">
        <DetailRow label="table_label" value={table?.table_label || (result.source_id ? `Table #${result.source_id}` : "Table")} />
        <DetailRow label="parse_status" value={table?.parse_status || "partial"} />
        <DetailRow label="source" value={table?.source || "text_candidate"} />
      </dl>
    );
  }
  return null;
}

function ResultCard({ result, paper }: { result: ExtractionResult; paper: PaperDetail }) {
  const confidence = confidencePercent(result.confidence);
  const sourceHash = result.source_type === "figure" && result.source_id
    ? `figure-${result.source_id}`
    : result.source_type === "table" && result.source_id
      ? `table-${result.source_id}`
      : "";

  return (
    <article className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <SourceBadge sourceType={result.source_type} sourceId={result.source_id} />
          {sourceHash ? <Link to={`/papers/${paper.id}#${sourceHash}`} className="text-xs font-medium text-slate-500 hover:text-slate-900">查看来源</Link> : null}
        </div>
        {confidence !== null ? <span className="text-xs font-medium text-slate-500">{confidence}%</span> : null}
      </div>
      {confidence !== null ? (
        <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-slate-900" style={{ width: `${confidence}%` }} />
        </div>
      ) : null}
      <ResultSourceDetails result={result} paper={paper} />
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{readableContent(result.content)}</p>
      {result.evidence ? (
        <div className="mt-3 rounded-xl bg-slate-50 p-3">
          <p className="mb-1 text-xs font-medium text-slate-500">证据</p>
          <p className="line-clamp-5 text-xs leading-5 text-slate-600">{result.evidence}</p>
        </div>
      ) : null}
    </article>
  );
}

function ResultBody({ job, paper }: { job: ExtractionJob; paper: PaperDetail }) {
  const results = job.results ?? [];
  const grouped = resultsByMetric(results);
  const metricKeys = resultMetricKeys(results);
  const sourceCounts = resultSourceCounts(results);

  if (!results.length) {
    return <div className="rounded-2xl bg-slate-50 p-10 text-center text-sm text-slate-400">暂无提取结果</div>;
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="h-fit rounded-2xl border border-slate-100 bg-white p-4 shadow-sm lg:sticky lg:top-20">
        <h2 className="mb-3 text-sm font-semibold text-slate-800">指标</h2>
        <nav className="space-y-1">
          {metricKeys.map((metric) => (
            <a key={metric} href={`#metric-${metric}`} className="flex items-center justify-between rounded-xl px-3 py-2 text-sm text-slate-600 transition hover:bg-slate-50 hover:text-slate-950">
              <span className="truncate">{fieldLabel(metric)}</span>
              <span className="text-xs text-slate-400">{grouped[metric].length}</span>
            </a>
          ))}
        </nav>
        <div className="mt-4 space-y-2 border-t border-slate-100 pt-4">
          {Object.entries(sourceCounts).map(([source, count]) => (
            <div key={source} className="flex items-center justify-between text-xs text-slate-500">
              <span className="inline-flex items-center gap-2">{sourceIcon(source)}{sourceLabel(source)}</span>
              <span>{count}</span>
            </div>
          ))}
        </div>
      </aside>

      <div className="space-y-4">
        {metricKeys.map((metric) => (
          <section id={`metric-${metric}`} key={metric} className="scroll-mt-20">
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-slate-900">{fieldLabel(metric)}</h2>
              <span className="text-xs text-slate-400">{grouped[metric].length} 条</span>
            </div>
            <div className="space-y-3">
              {grouped[metric].map((result) => <ResultCard key={result.id} result={result} paper={paper} />)}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

export function PaperExtractionResultPage() {
  const paperId = Number(useParams().id);
  const [searchParams] = useSearchParams();
  const selectedJobId = Number(searchParams.get("job"));
  const hasSelectedJob = Number.isFinite(selectedJobId) && selectedJobId > 0;
  const queryClient = useQueryClient();

  const paperQuery = useQuery({
    queryKey: ["paper", paperId],
    queryFn: () => getPaper(paperId),
    enabled: Number.isFinite(paperId),
    refetchInterval: (queryState) => shouldPollPaper(queryState.state.data) ? 2000 : false
  });
  const jobQuery = useQuery({
    queryKey: ["extraction", selectedJobId],
    queryFn: () => getExtraction(selectedJobId),
    enabled: hasSelectedJob,
    refetchInterval: (queryState) => isExtractionBusy(queryState.state.data?.status) ? 2000 : false
  });
  const retryMutation = useMutation({
    mutationFn: (jobId: number) => retryExtraction(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper", paperId] });
      queryClient.invalidateQueries({ queryKey: ["extraction", selectedJobId] });
    }
  });

  const paper = paperQuery.data;
  const job = hasSelectedJob ? jobQuery.data : paper?.latest_extraction_job;
  const loading = paperQuery.isLoading || (hasSelectedJob && jobQuery.isLoading);

  if (loading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
        <Button asChild variant="ghost" size="sm" className="mb-3 rounded-xl px-2 text-slate-500">
          <Link to={`/papers/${paper.id}/extraction`}><ArrowLeft className="h-4 w-4" />提取任务</Link>
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              {job ? <ExtractionStatusBadge status={job.status} /> : null}
              {job ? <span className="text-xs text-slate-400">任务 #{job.id} · {formatChinaDateTime(job.updated_at)}</span> : null}
            </div>
            <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight text-slate-950">{paper.title}</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" className="rounded-xl border-slate-200 shadow-none">
              <Link to={`/papers/${paper.id}`}><FileText className="h-4 w-4" />论文详情</Link>
            </Button>
            <Button variant="outline" className="rounded-xl border-slate-200 shadow-none" onClick={() => { paperQuery.refetch(); jobQuery.refetch(); }} disabled={paperQuery.isFetching || jobQuery.isFetching}>
              {paperQuery.isFetching || jobQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </Button>
          </div>
        </div>
      </section>

      {!job ? (
        <section className="rounded-2xl border border-slate-100 bg-white p-10 text-center shadow-sm">
          <BarChart3 className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-3 text-sm text-slate-500">暂无提取结果</p>
          <Button asChild className="mt-4 rounded-xl">
            <Link to={`/papers/${paper.id}/extraction`}>创建提取任务</Link>
          </Button>
        </section>
      ) : null}

      {job && isExtractionBusy(job.status) ? (
        <section className="rounded-2xl border border-slate-100 bg-white p-10 text-center shadow-sm">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-slate-400" />
          <p className="mt-3 text-sm font-medium text-slate-700">提取任务正在执行</p>
          <p className="mt-1 text-xs text-slate-400">状态会自动刷新</p>
        </section>
      ) : null}

      {job?.status === "failed" ? (
        <Alert variant="destructive" className="rounded-xl">
          <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{job.error_message ?? "提取失败"}</span>
            <Button type="button" size="sm" variant="outline" className="rounded-xl border-red-200 bg-white text-red-700 shadow-none hover:bg-red-50" onClick={() => retryMutation.mutate(job.id)} disabled={retryMutation.isPending}>
              {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}
              重试
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {job?.status === "done" ? <ResultBody job={job} paper={paper} /> : null}
    </div>
  );
}
