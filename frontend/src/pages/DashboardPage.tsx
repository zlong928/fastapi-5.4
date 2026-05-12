import { useQuery } from "@tanstack/react-query";
import { Activity, FileUp, ListChecks, Server } from "lucide-react";
import { Link } from "react-router-dom";
import { TaskCard } from "@/components/TaskCard";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
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
          <Button asChild>
          <Link to="/upload" className="gap-2">
            <FileUp className="h-4 w-4" /> Upload
          </Link>
          </Button>
          <Button asChild variant="outline">
          <Link to="/tasks" className="gap-2">
            <ListChecks className="h-4 w-4" /> Tasks
          </Link>
          </Button>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-5">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500">API Status</span>
            <Server className="h-5 w-5 text-slate-400" />
          </div>
          <p className={`mt-4 text-2xl font-semibold ${health.isError ? "text-red-600" : "text-emerald-600"}`}>{health.isLoading ? "Checking" : health.data?.status ?? "Offline"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500">Queued Tasks</span>
            <Activity className="h-5 w-5 text-slate-400" />
          </div>
          <p className="mt-4 text-2xl font-semibold">{health.data?.queued_tasks ?? "-"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500">Tracked Tasks</span>
            <ListChecks className="h-5 w-5 text-slate-400" />
          </div>
          <p className="mt-4 text-2xl font-semibold">{health.data?.tracked_tasks ?? tasks.data?.length ?? "-"}</p>
          </CardContent>
        </Card>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">Recent tasks</h2>
          <Button asChild variant="link" className="px-0">
            <Link to="/tasks">View all</Link>
          </Button>
        </div>
        {tasks.isLoading ? <Skeleton className="h-24 w-full" /> : null}
        {tasks.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{tasks.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {!tasks.isLoading && !recentTasks.length ? <div className="rounded-lg border border-dashed border-border bg-card p-10 text-center text-slate-500">No recent tasks yet</div> : null}
        <div className="grid gap-4 md:grid-cols-3">
          {recentTasks.map((task) => <TaskCard key={task.task_id} task={task} />)}
        </div>
      </section>
    </div>
  );
}
