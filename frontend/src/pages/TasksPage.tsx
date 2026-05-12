import { RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { TaskTable } from "@/components/TaskTable";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTasks } from "@/hooks/useTasks";

export function TasksPage() {
  const { data = [], error, isError, isLoading, isFetching, refetch } = useTasks();
  const [clearedTasks, setClearedTasks] = useState<Set<string>>(new Set());

  const handleClear = () => {
    setClearedTasks(new Set(data.map((task) => task.task_id)));
  };

  const displayedTasks = data.filter((task) => !clearedTasks.has(task.task_id));

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Tasks</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Task queue</h1>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => refetch()}
            className="gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handleClear}
            className="gap-2"
            disabled={displayedTasks.length === 0}
          >
            <Trash2 className="h-4 w-4" /> Clear
          </Button>
        </div>
      </div>

      {isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {isError ? (
        <Alert variant="destructive">
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ) : null}
      {!isLoading && !isError ? <TaskTable tasks={displayedTasks} /> : null}
    </div>
  );
}
