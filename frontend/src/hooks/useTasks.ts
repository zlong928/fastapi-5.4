import { useQuery } from "@tanstack/react-query";
import { searchTasks } from "@/lib/api";
import { TaskListParams } from "@/lib/types";

export function useTasks(params: TaskListParams = {}) {
  return useQuery({
    queryKey: ["tasks", params],
    queryFn: () => searchTasks(params),
    staleTime: 1_000,
    gcTime: 5 * 60_000,
    refetchInterval: (query) => {
      const tasks = query.state.data?.items ?? [];
      return tasks.some((task) => task.status === "queued" || task.status === "running" || task.status === "processing") ? 2_000 : false;
    },
    throwOnError: false
  });
}
