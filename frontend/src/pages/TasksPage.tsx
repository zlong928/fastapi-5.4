import { RefreshCw, Search, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTasks } from "@/hooks/useTasks";
import { clearTasks } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { TaskListParams, TaskRecord } from "@/lib/types";

const ITEMS_PER_PAGE = 12;

function taskTypeLabel(task: TaskRecord) {
  if (task.task_kind === "document_parse") return "解析";
  if (task.task_kind === "basic_file_processing") return "处理";
  if (task.task_kind === "document_embedding") return "Embedding";
  return task.task_kind;
}

export function TasksPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<TaskListParams>({
    page: 1,
    size: ITEMS_PER_PAGE,
    sort_by: "updated_at",
    sort_order: "desc"
  });

  const queryParams = useMemo(() => ({ ...filters, page, size: ITEMS_PER_PAGE }), [filters, page]);
  const { data, error, isError, isLoading, isFetching, refetch } = useTasks(queryParams);
  const tasks = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / ITEMS_PER_PAGE));
  const queryClient = useQueryClient();

  const clearMutation = useMutation({
    mutationFn: clearTasks,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  function updateFilter<K extends keyof TaskListParams>(key: K, value: TaskListParams[K]) {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  const handleClear = () => {
    if (confirm("清空任务记录？")) clearMutation.mutate();
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <section className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">任务</h1>
          <p className="mt-1 text-sm text-slate-400">{total} 条</p>
        </div>

        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={() => refetch()}>
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
          <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={handleClear} disabled={tasks.length === 0 || clearMutation.isPending}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </section>

      <section className="flex flex-wrap gap-2 rounded-3xl border border-slate-100 bg-white p-2">
        <label className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={filters.q ?? ""}
            onChange={(event) => updateFilter("q", event.target.value)}
            placeholder="搜索"
            className="h-10 w-full rounded-2xl border border-transparent bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-slate-200 focus:bg-white"
          />
        </label>

        <select value={filters.status ?? ""} onChange={(event) => updateFilter("status", event.target.value || undefined)} className="h-10 rounded-2xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none">
          <option value="">状态</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="succeeded">Succeeded</option>
          <option value="failed">Failed</option>
        </select>

        <select value={filters.kind ?? ""} onChange={(event) => updateFilter("kind", event.target.value || undefined)} className="h-10 rounded-2xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none">
          <option value="">类型</option>
          <option value="document_parse">解析</option>
          <option value="basic_file_processing">处理</option>
          <option value="document_embedding">Embedding</option>
        </select>
      </section>

      {isLoading ? <Skeleton className="h-40 w-full rounded-3xl" /> : null}

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

      {!isLoading && !isError ? (
        tasks.length ? (
          <div className="space-y-2">
            {tasks.map((task) => (
              <TaskFlowItem key={task.task_id} task={task} />
            ))}
          </div>
        ) : (
          <div className="flex min-h-[320px] items-center justify-center rounded-3xl border border-dashed border-slate-100 text-sm text-slate-400">
            无任务
          </div>
        )
      ) : null}

      <div className="flex items-center justify-between pt-2 text-sm text-slate-400">
        <span>{page} / {totalPages}</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" disabled={page === 1} onClick={() => setPage((current) => current - 1)}>上一页</Button>
          <Button variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>下一页</Button>
        </div>
      </div>
    </div>
  );
}

function TaskFlowItem({ task }: { task: TaskRecord }) {
  const href = task.task_kind === "document_parse" && task.document_id ? `/documents/${task.document_id}` : `/tasks/${task.task_id}`;

  return (
    <Link to={href} className="block rounded-2xl border border-slate-100 bg-white px-4 py-3 transition hover:bg-slate-50">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium text-slate-950">{task.file_name ?? task.filename ?? task.task_id}</p>
            <StatusBadge status={task.status} />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
            <span>{taskTypeLabel(task)}</span>
            <span>{task.progress}%</span>
            <span>{formatChinaDateTime(task.updated_at)}</span>
          </div>

          {task.error ? (
            <p className="mt-2 line-clamp-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-600">{task.error}</p>
          ) : null}
        </div>
      </div>
    </Link>
  );
}
