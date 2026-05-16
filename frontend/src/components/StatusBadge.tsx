import { Badge } from "@/components/ui/badge";
import { TaskStatus } from "@/lib/types";

export function StatusBadge({ status }: { status: TaskStatus }) {
  const variant = status === "success" || status === "parsed" || status === "succeeded" ? "success" : status === "processing" || status === "running" ? "processing" : status === "failed" ? "destructive" : "queued";
  return <Badge variant={variant}>{status}</Badge>;
}
