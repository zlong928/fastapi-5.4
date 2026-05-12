import { useQuery } from "@tanstack/react-query";
import { getTasks } from "@/lib/api";

export function useTasks() {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: getTasks,
    refetchInterval: (query) => {
      const tasks = query.state.data ?? [];
      return tasks.some((task) => task.status === "queued" || task.status === "processing") ? 2_000 : false;
    }
  });
}
