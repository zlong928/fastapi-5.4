import { Download, FileText, RefreshCw } from "lucide-react";
import { useParams } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { useTask } from "@/hooks/useTask";
import { API_BASE_URL } from "@/lib/api";

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString() : "-";
}

function renderResult(result: unknown) {
  if (!result) {
    return <div className="rounded-lg border border-dashed border-border bg-slate-50 p-8 text-center text-slate-500">No result content available yet</div>;
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
        <button type="button" onClick={() => refetch()} className="inline-flex items-center gap-2 rounded-md border border-border bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50">
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {isLoading ? <div className="rounded-lg bg-white p-8 text-slate-500">Loading task...</div> : null}
      {isError ? <div className="rounded-lg bg-red-50 p-4 text-red-700">{error.message}</div> : null}

      {task ? (
        <>
          <section className="rounded-lg border border-border bg-white p-6 shadow-soft">
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
              <div><dt className="text-sm text-slate-500">Created</dt><dd className="mt-1 font-medium">{formatDate(task.created_at)}</dd></div>
              <div><dt className="text-sm text-slate-500">Updated</dt><dd className="mt-1 font-medium">{formatDate(task.updated_at)}</dd></div>
              <div><dt className="text-sm text-slate-500">File size</dt><dd className="mt-1 font-medium">{task.file_size ? `${task.file_size} bytes` : "-"}</dd></div>
              <div><dt className="text-sm text-slate-500">File type</dt><dd className="mt-1 font-medium">{task.file_type ?? "-"}</dd></div>
            </dl>
            {task.error ? <div className="mt-6 rounded-md bg-red-50 p-4 text-red-700">{task.error}</div> : null}
          </section>

          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold">Result</h2>
              {task.result ? (
                <a href={`${API_BASE_URL}/tasks/${encodeURIComponent(task.task_id)}/result`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-md border border-border bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50">
                  <Download className="h-4 w-4" /> Open JSON
                </a>
              ) : null}
            </div>
            {renderResult(task.result)}
          </section>
        </>
      ) : null}
    </div>
  );
}
