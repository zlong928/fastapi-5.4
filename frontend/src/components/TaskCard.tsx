import { CalendarClock, FileText } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { TaskRecord } from "@/lib/types";

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString() : "Unknown";
}

export function TaskCard({ task }: { task: TaskRecord }) {
  return (
    <Link to={`/tasks/${task.task_id}`} className="block transition hover:-translate-y-0.5">
      <Card className="hover:shadow-lg">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <FileText className="h-4 w-4" />
                <span className="truncate">{task.file_name ?? task.filename ?? "Unnamed file"}</span>
              </div>
              <p className="mt-2 break-all font-mono text-sm text-slate-900">{task.task_id}</p>
            </div>
            <StatusBadge status={task.status} />
          </div>
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarClock className="h-4 w-4" />
            {formatDate(task.updated_at ?? task.created_at)}
          </div>
          {task.error ? <Alert variant="destructive" className="mt-3">{task.error}</Alert> : null}
        </CardContent>
      </Card>
    </Link>
  );
}
