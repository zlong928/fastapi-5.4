import { RefreshCw } from "lucide-react";
import { TaskTable } from "@/components/TaskTable";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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
        <Button
          type="button"
          variant="outline"
          onClick={() => refetch()}
          className="gap-2"
        >
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {isError ? (
        <Alert variant="destructive">
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ) : null}
      {!isLoading && !isError ? <TaskTable tasks={data} /> : null}
    </div>
  );
}
