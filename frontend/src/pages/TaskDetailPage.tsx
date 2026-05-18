import { Download, FileText, RefreshCw } from "lucide-react";
import { useParams } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTask } from "@/hooks/useTask";
import { API_BASE_URL } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";

function renderResult(result: unknown) {
  if (!result) {
    return <div className="rounded-lg border border-dashed border-border bg-card p-8 text-center text-slate-500">No result content available yet</div>;
  }
  return <pre className="max-h-[520px] overflow-auto rounded-lg bg-slate-950 p-4 text-sm text-slate-50">{JSON.stringify(result, null, 2)}</pre>;
}

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const taskId = id ?? "";
  const { data: task, error, isError, isLoading, isFetching, refetch } = useTask(taskId);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Task detail</p>
          <h1 className="mt-2 break-all text-3xl font-semibold tracking-tight">{taskId}</h1>
        </div>
        <Button type="button" variant="outline" onClick={() => refetch()} className="gap-2">
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {isError ? (
        <Alert variant="destructive">
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ) : null}

      {task ? (
        <>
          <Card>
            <CardContent className="p-6">
            <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
              <div>
                <div className="flex items-center gap-2 text-slate-500">
                  <FileText className="h-5 w-5" />
                  <span>{task.file_name ?? task.filename ?? "Unnamed file"}</span>
                </div>
                <p className="mt-3 break-all font-mono text-sm text-slate-700">{task.task_id}</p>
              </div>
              <StatusBadge status={task.status} />
            </div>
            <dl className="mt-6 grid gap-4 md:grid-cols-2">
              <div><dt className="text-sm text-slate-500">Created</dt><dd className="mt-1 font-medium">{formatChinaDateTime(task.created_at)}</dd></div>
              <div><dt className="text-sm text-slate-500">Updated</dt><dd className="mt-1 font-medium">{formatChinaDateTime(task.updated_at)}</dd></div>
              <div><dt className="text-sm text-slate-500">File size</dt><dd className="mt-1 font-medium">{task.file_size ? `${task.file_size} bytes` : "-"}</dd></div>
              <div><dt className="text-sm text-slate-500">File type</dt><dd className="mt-1 font-medium">{task.file_type ?? "-"}</dd></div>
            </dl>
            {task.error ? (
              <Alert variant="destructive" className="mt-6">
                <AlertDescription>{task.error}</AlertDescription>
              </Alert>
            ) : null}
            </CardContent>
          </Card>

          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold">Result</h2>
              {task.result ? (
                <Button asChild variant="outline" size="sm" className="gap-2">
                <a href={`${API_BASE_URL}/tasks/${encodeURIComponent(task.task_id)}/result`} target="_blank" rel="noreferrer">
                  <Download className="h-4 w-4" /> Open JSON
                </a>
                </Button>
              ) : null}
            </div>
            {renderResult(task.result)}
          </section>
        </>
      ) : null}
    </div>
  );
}
