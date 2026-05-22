import { RefreshCw, Search, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { TaskTable } from "@/components/TaskTable";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTasks } from "@/hooks/useTasks";
import { clearTasks } from "@/lib/api";
import { TaskListParams } from "@/lib/types";

const ITEMS_PER_PAGE = 10;

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

  function clearFilters() {
    setPage(1);
    setFilters({ page: 1, size: ITEMS_PER_PAGE, sort_by: "updated_at", sort_order: "desc" });
  }

  const handleClear = () => {
    if (confirm("Clear task records from your task list? Document history remains attached to documents.")) {
      clearMutation.mutate();
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Task Center</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">任务中心</h1>
          <p className="mt-2 text-sm text-slate-500">查看上传、解析、向量化等后台处理状态；知识库负责资料管理，工具页只放功能入口。</p>
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
            disabled={tasks.length === 0 || clearMutation.isPending}
          >
            <Trash2 className="h-4 w-4" /> Clear
          </Button>
        </div>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="md:col-span-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Search</span>
            <div className="relative mt-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={filters.q ?? ""}
                onChange={(event) => updateFilter("q", event.target.value)}
                placeholder="Task ID, file name, title, or error"
                className="h-10 w-full rounded-md border border-slate-300 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</span>
            <select
              value={filters.status ?? ""}
              onChange={(event) => updateFilter("status", event.target.value || undefined)}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="">All statuses</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Type</span>
            <select
              value={filters.kind ?? ""}
              onChange={(event) => updateFilter("kind", event.target.value || undefined)}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="">All types</option>
              <option value="document_parse">Document parse</option>
              <option value="basic_file_processing">File task</option>
              <option value="document_embedding">Document embedding</option>
              <option value="document_summary">Document summary</option>
            </select>
          </label>
          <label className="md:col-span-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sort</span>
            <select
              value={`${filters.sort_by}:${filters.sort_order}`}
              onChange={(event) => {
                const [sortBy, sortOrder] = event.target.value.split(":");
                setPage(1);
                setFilters((current) => ({
                  ...current,
                  sort_by: sortBy as TaskListParams["sort_by"],
                  sort_order: sortOrder as "asc" | "desc"
                }));
              }}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="updated_at:desc">Recently updated</option>
              <option value="created_at:desc">Newest first</option>
              <option value="file_name:asc">File name A-Z</option>
              <option value="status:asc">Status</option>
              <option value="kind:asc">Type</option>
              <option value="progress:desc">Progress high-low</option>
            </select>
          </label>
          <div className="flex items-end justify-between gap-3 md:col-span-2">
            <p className="pb-2 text-sm text-slate-500">{total} task(s)</p>
            <Button type="button" variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>
          </div>
        </div>
      </section>

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
      {!isLoading && !isError ? <TaskTable tasks={tasks} /> : null}

      <div className="flex items-center justify-between border-t border-slate-200 pt-4">
        <p className="text-sm text-slate-600">Page {page} of {totalPages}</p>
        <div className="flex gap-2">
          <Button variant="outline" disabled={page === 1} onClick={() => setPage((current) => current - 1)}>Previous</Button>
          <Button variant="outline" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>Next</Button>
        </div>
      </div>
    </div>
  );
}
