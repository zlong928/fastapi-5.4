import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Eye, FileText, Loader2, RefreshCw, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getExtractions, retryExtraction } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { ExtractionJobListItem } from "@/lib/types";
import { ExtractionStatusBadge, extractionStatusLabel, isExtractionBusy } from "@/pages/paperShared";

function ExtractionJobCard({ job, onRetry, retrying }: { job: ExtractionJobListItem; onRetry: (jobId: number) => void; retrying: boolean }) {
  return (
    <article className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
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
          <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-700">{job.query}</p>
          <dl className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="font-medium text-slate-600">paper_title</dt>
              <dd className="mt-1 truncate">{job.paper_title}</dd>
            </div>
            <div>
              <dt className="font-medium text-slate-600">created_at</dt>
              <dd className="mt-1">{formatChinaDateTime(job.created_at)}</dd>
            </div>
            <div>
              <dt className="font-medium text-slate-600">status</dt>
              <dd className="mt-1">{extractionStatusLabel(job.status)}</dd>
            </div>
            <div>
              <dt className="font-medium text-slate-600">result_count</dt>
              <dd className="mt-1">{job.result_count}</dd>
            </div>
          </dl>
          {job.error_message ? (
            <div className="mt-3 flex gap-2 rounded-xl bg-red-50 p-3 text-xs leading-5 text-red-700">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="line-clamp-3">{job.error_message}</span>
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button asChild size="sm" variant="outline" className="rounded-xl border-slate-200 shadow-none">
            <Link to={`/papers/${job.paper_id}/results?job=${job.id}`}><Eye className="h-4 w-4" />查看结果</Link>
          </Button>
          {job.status === "failed" ? (
            <Button type="button" size="sm" variant="outline" className="rounded-xl border-slate-200 shadow-none" onClick={() => onRetry(job.id)} disabled={retrying}>
              {retrying ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              重试
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function ExtractionsPage() {
  const queryClient = useQueryClient();
  const jobsQuery = useQuery({
    queryKey: ["extractions"],
    queryFn: getExtractions,
    refetchInterval: (queryState) => (queryState.state.data ?? []).some((job) => isExtractionBusy(job.status)) ? 2000 : false
  });
  const retryMutation = useMutation({
    mutationFn: (jobId: number) => retryExtraction(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["extractions"] })
  });

  const jobs = jobsQuery.data ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-500">提取任务</p>
            <h1 className="mt-2 text-2xl font-semibold leading-tight tracking-tight text-slate-950">所有论文提取任务</h1>
          </div>
          <Button variant="outline" className="rounded-xl border-slate-200 shadow-none" onClick={() => jobsQuery.refetch()} disabled={jobsQuery.isFetching}>
            {jobsQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </Button>
        </div>
      </section>

      {jobsQuery.error ? (
        <Alert variant="destructive" className="rounded-xl">
          <AlertDescription>{jobsQuery.error instanceof Error ? jobsQuery.error.message : "提取任务加载失败"}</AlertDescription>
        </Alert>
      ) : null}

      <section className="space-y-3">
        {jobs.map((job) => (
          <ExtractionJobCard
            key={job.id}
            job={job}
            onRetry={(jobId) => retryMutation.mutate(jobId)}
            retrying={retryMutation.isPending}
          />
        ))}
        {jobsQuery.isLoading ? <div className="rounded-2xl bg-slate-50 p-10 text-center text-sm text-slate-400">加载中</div> : null}
        {!jobsQuery.isLoading && !jobs.length ? <div className="rounded-2xl bg-slate-50 p-10 text-center text-sm text-slate-400">暂无提取任务</div> : null}
      </section>
    </div>
  );
}
