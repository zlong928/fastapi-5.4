import { RefreshCw, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { TaskTable } from "@/components/TaskTable";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTasks } from "@/hooks/useTasks";
import { clearTasks } from "@/lib/api";

export function TasksPage() {
  const { data = [], error, isError, isLoading, isFetching, refetch } = useTasks();
  const queryClient = useQueryClient();
  const clearMutation = useMutation({
    mutationFn: clearTasks,
    onSuccess: () => {
      queryClient.setQueryData(["tasks"], []);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  const handleClear = () => {
    clearMutation.mutate();
  };

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
            disabled={data.length === 0 || clearMutation.isPending}
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
      {clearMutation.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{clearMutation.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {!isLoading && !isError ? <TaskTable tasks={data} /> : null}
    </div>
  );
}
