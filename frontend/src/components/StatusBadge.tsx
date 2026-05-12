import { TaskStatus } from "@/lib/types";

const styles: Record<string, string> = {
  queued: "bg-slate-100 text-slate-700 ring-slate-200",
  processing: "bg-blue-50 text-blue-700 ring-blue-200",
  success: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-red-200"
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${styles[status] ?? styles.queued}`}>
      {status}
    </span>
  );
}
