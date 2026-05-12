import { CalendarClock, FileText } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { TaskRecord } from "@/lib/types";

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString() : "Unknown";
}

export function TaskCard({ task }: { task: TaskRecord }) {
  return (
    <Link to={`/tasks/${task.task_id}`} className="block rounded-lg border border-border bg-white p-5 shadow-soft transition hover:-translate-y-0.5 hover:shadow-lg">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <FileText className="h-4 w-4" />
            <span className="truncate">{task.file_name ?? task.filename ?? "Unnamed file"}</span>
          </div>
          <p className="mt-2 break-all font-mono text-sm text-slate-900">{task.task_id}</p>
        </div>
        <StatusBadge status={task.status} />
      </div>
      <div className="mt-4 flex items-center gap-2 text-sm text-slate-500">
        <CalendarClock className="h-4 w-4" />
        {formatDate(task.updated_at ?? task.created_at)}
      </div>
      {task.error ? <p className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-700">{task.error}</p> : null}
    </Link>
  );
}
