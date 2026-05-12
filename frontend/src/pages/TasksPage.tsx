import { RefreshCw } from "lucide-react";
import { TaskTable } from "@/components/TaskTable";
import { useTasks } from "@/hooks/useTasks";

export function TasksPage() {
  const { data = [], error, isError, isLoading, isFetching, refetch } = useTasks();

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Tasks</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Task queue</h1>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="inline-flex items-center gap-2 rounded-md border border-border bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
        >
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {isLoading ? <div className="rounded-lg bg-white p-8 text-slate-500">Loading tasks...</div> : null}
      {isError ? <div className="rounded-lg bg-red-50 p-4 text-red-700">{error.message}</div> : null}
      {!isLoading && !isError ? <TaskTable tasks={data} /> : null}
    </div>
  );
}
