import { useQuery } from "@tanstack/react-query";
import { Activity, FileUp, ListChecks, Server } from "lucide-react";
import { Link } from "react-router-dom";
import { TaskCard } from "@/components/TaskCard";
import { useTasks } from "@/hooks/useTasks";
import { healthCheck } from "@/lib/api";

export function DashboardPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: healthCheck, refetchInterval: 10_000 });
  const tasks = useTasks();
  const recentTasks = (tasks.data ?? []).slice(-3).reverse();

  return (
    <div className="space-y-8">
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Dashboard</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">File Processing Service</h1>
          <p className="mt-2 max-w-2xl text-slate-600">Upload PDFs, watch queued jobs move through the worker, and inspect processing results from one clean workspace.</p>
        </div>
        <div className="flex gap-3">
          <Link to="/upload" className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
            <FileUp className="h-4 w-4" /> Upload
          </Link>
          <Link to="/tasks" className="inline-flex items-center gap-2 rounded-md border border-border bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50">
            <ListChecks className="h-4 w-4" /> Tasks
          </Link>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-border bg-white p-5 shadow-soft">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500">API Status</span>
            <Server className="h-5 w-5 text-slate-400" />
          </div>
          <p className={`mt-4 text-2xl font-semibold ${health.isError ? "text-red-600" : "text-emerald-600"}`}>{health.isLoading ? "Checking" : health.data?.status ?? "Offline"}</p>
        </div>
        <div className="rounded-lg border border-border bg-white p-5 shadow-soft">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500">Queued Tasks</span>
            <Activity className="h-5 w-5 text-slate-400" />
          </div>
          <p className="mt-4 text-2xl font-semibold">{health.data?.queued_tasks ?? "-"}</p>
        </div>
        <div className="rounded-lg border border-border bg-white p-5 shadow-soft">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500">Tracked Tasks</span>
            <ListChecks className="h-5 w-5 text-slate-400" />
          </div>
          <p className="mt-4 text-2xl font-semibold">{health.data?.tracked_tasks ?? tasks.data?.length ?? "-"}</p>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">Recent tasks</h2>
          <Link to="/tasks" className="text-sm font-medium text-blue-700 hover:text-blue-900">View all</Link>
        </div>
        {tasks.isLoading ? <div className="rounded-lg bg-white p-8 text-slate-500">Loading tasks...</div> : null}
        {tasks.isError ? <div className="rounded-lg bg-red-50 p-4 text-red-700">{tasks.error.message}</div> : null}
        {!tasks.isLoading && !recentTasks.length ? <div className="rounded-lg border border-dashed border-border bg-white p-10 text-center text-slate-500">No recent tasks yet</div> : null}
        <div className="grid gap-4 md:grid-cols-3">
          {recentTasks.map((task) => <TaskCard key={task.task_id} task={task} />)}
        </div>
      </section>
    </div>
  );
}
