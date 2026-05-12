import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { TaskRecord } from "@/lib/types";

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString() : "-";
}

export function TaskTable({ tasks }: { tasks: TaskRecord[] }) {
  if (!tasks.length) {
    return <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-slate-500">No tasks found</div>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-white shadow-soft">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Task ID</th>
              <th className="px-4 py-3">File name</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Updated</th>
              <th className="px-4 py-3">Error</th>
              <th className="px-4 py-3">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {tasks.map((task) => (
              <tr key={task.task_id} className="align-top">
                <td className="max-w-[220px] break-all px-4 py-3 font-mono text-xs text-slate-700">{task.task_id}</td>
                <td className="px-4 py-3">{task.file_name ?? task.filename ?? "-"}</td>
                <td className="px-4 py-3"><StatusBadge status={task.status} /></td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-500">{formatDate(task.created_at)}</td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-500">{formatDate(task.updated_at)}</td>
                <td className="max-w-[260px] px-4 py-3 text-red-600">{task.error ?? "-"}</td>
                <td className="px-4 py-3">
                  <Link to={`/tasks/${task.task_id}`} className="inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium text-blue-700 hover:bg-blue-50">
                    View <ExternalLink className="h-3.5 w-3.5" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
