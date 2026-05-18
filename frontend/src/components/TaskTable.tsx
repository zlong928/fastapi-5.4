import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatChinaDateTime } from "@/lib/time";
import { TaskRecord } from "@/lib/types";

function taskTypeLabel(task: TaskRecord) {
  if (task.task_kind === "document_parse") return "Document parse";
  if (task.task_kind === "basic_file_processing") return "File task";
  return task.task_kind;
}

export function TaskTable({ tasks }: { tasks: TaskRecord[] }) {
  if (!tasks.length) {
    return <Card className="border-dashed p-10 text-center text-muted-foreground">No tasks found</Card>;
  }

  return (
    <Card className="overflow-hidden">
      <Table>
        <TableHeader className="bg-muted/60">
          <TableRow>
            <TableHead>Task ID</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>File name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Progress</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Updated</TableHead>
            <TableHead>Error</TableHead>
            <TableHead>Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.map((task) => (
            <TableRow key={task.task_id} className="align-top">
              <TableCell className="max-w-[220px] break-all font-mono text-xs text-slate-700">{task.task_id}</TableCell>
              <TableCell>{taskTypeLabel(task)}</TableCell>
              <TableCell>{task.file_name ?? task.filename ?? "-"}</TableCell>
              <TableCell><StatusBadge status={task.status} /></TableCell>
              <TableCell>{`${task.progress}%`}</TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">{formatChinaDateTime(task.created_at)}</TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">{formatChinaDateTime(task.updated_at)}</TableCell>
              <TableCell className="max-w-[260px] text-red-600">{task.error ?? "-"}</TableCell>
              <TableCell>
                {task.task_kind === "document_parse" && !task.document_id ? (
                  <Button type="button" variant="ghost" size="sm" disabled title="Document record is unavailable">
                    View
                  </Button>
                ) : (
                  <Button asChild variant="ghost" size="sm" className="text-blue-700 hover:text-blue-900">
                    <Link to={task.task_kind === "document_parse" ? `/documents/${task.document_id}` : `/tasks/${task.task_id}`}>
                      View <ExternalLink className="h-3.5 w-3.5" />
                    </Link>
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}
