import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TaskRecord } from "@/lib/types";

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString() : "-";
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
            <TableHead>File name</TableHead>
            <TableHead>Status</TableHead>
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
              <TableCell>{task.file_name ?? task.filename ?? "-"}</TableCell>
              <TableCell><StatusBadge status={task.status} /></TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(task.created_at)}</TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(task.updated_at)}</TableCell>
              <TableCell className="max-w-[260px] text-red-600">{task.error ?? "-"}</TableCell>
              <TableCell>
                <Button asChild variant="ghost" size="sm" className="text-blue-700 hover:text-blue-900">
                  <Link to={`/tasks/${task.task_id}`}>
                    View <ExternalLink className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}
