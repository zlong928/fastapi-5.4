import { Badge } from "@/components/ui/badge";
import { TaskStatus } from "@/lib/types";

export function StatusBadge({ status }: { status: TaskStatus }) {
  const variant = status === "success" ? "success" : status === "processing" ? "processing" : status === "failed" ? "destructive" : "queued";
  return <Badge variant={variant}>{status}</Badge>;
}
