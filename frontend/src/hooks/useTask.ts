import { useQuery } from "@tanstack/react-query";
import { getTask } from "@/lib/api";

export function useTask(taskId: string) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => getTask(taskId),
    enabled: Boolean(taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "processing" ? 2_000 : false;
    }
  });
}
