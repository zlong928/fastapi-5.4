import { Download, FileText, RefreshCw } from "lucide-react";
import { useParams } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTask } from "@/hooks/useTask";
import { API_BASE_URL } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";

function renderResult(result: unknown) {
  if (!result) {
    return <div className="rounded-2xl border border-dashed border-slate-100 bg-slate-50 p-8 text-center text-sm text-slate-400">无结果</div>;
  }
  return <pre className="max-h-[520px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">{JSON.stringify(result, null, 2)}</pre>;
}

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const taskId = id ?? "";
  const { data: task, error, isError, isLoading, isFetching, refetch } = useTask(taskId);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="break-all text-2xl font-semibold tracking-tight">{task?.file_name ?? task?.filename ?? taskId}</h1>
          <p className="mt-1 break-all text-xs text-slate-400">{taskId}</p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => refetch()} className="rounded-xl border-slate-100 shadow-none">
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {isLoading ? <Skeleton className="h-64 w-full rounded-3xl" /> : null}
      {isError ? (
        <Alert variant="destructive">
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ) : null}

      {task ? (
        <>
          <div className="rounded-3xl border border-slate-100 bg-white p-4">
            <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
              <div>
                <div className="flex items-center gap-2 text-slate-500">
                  <FileText className="h-5 w-5" />
                  <span>{task.file_name ?? task.filename ?? "未命名"}</span>
                </div>
                <p className="mt-3 break-all font-mono text-xs text-slate-500">{task.task_id}</p>
              </div>
              <StatusBadge status={task.status} />
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              <InfoRow label="创建" value={formatChinaDateTime(task.created_at)} />
              <InfoRow label="更新" value={formatChinaDateTime(task.updated_at)} />
              <InfoRow label="大小" value={task.file_size ? `${task.file_size} bytes` : "-"} />
              <InfoRow label="类型" value={task.file_type ?? "-"} />
            </div>
            {task.error ? (
              <Alert variant="destructive" className="mt-4 rounded-2xl border-red-100">
                <AlertDescription>{task.error}</AlertDescription>
              </Alert>
            ) : null}
          </div>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">结果</h2>
              {task.result ? (
                <Button asChild variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none">
                  <a href={`${API_BASE_URL}/tasks/${encodeURIComponent(task.task_id)}/result`} target="_blank" rel="noreferrer">
                    <Download className="h-4 w-4" />
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

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl px-3 py-2 hover:bg-slate-50">
      <span className="text-sm text-slate-400">{label}</span>
      <span className="truncate text-sm text-slate-700">{value}</span>
    </div>
  );
}
