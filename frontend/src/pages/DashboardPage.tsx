import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, Clock, FileText, PieChart, Server } from "lucide-react";
import { Link } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getStatistics, healthCheck } from "@/lib/api";

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function DashboardPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: healthCheck, refetchInterval: 10_000 });
  const stats = useQuery({ queryKey: ["statistics"], queryFn: getStatistics, refetchInterval: 15_000 });

  return (
    <div className="space-y-8">
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Dashboard</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Second Brain</h1>
          <p className="mt-2 max-w-2xl text-slate-600">Private documents, parser state, tags, and operational health in one workspace.</p>
        </div>
        <div className="flex gap-3">
          <Button asChild>
            <Link to="/knowledge">上传资料</Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/tasks">任务中心</Link>
          </Button>
        </div>
      </section>

      {stats.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{stats.error.message}</AlertDescription>
        </Alert>
      ) : null}

      <section className="grid gap-4 md:grid-cols-5">
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">API</span>
              <Server className="h-5 w-5 text-slate-400" />
            </div>
            <p className={`mt-4 text-2xl font-semibold ${health.isError ? "text-red-600" : "text-emerald-600"}`}>{health.isLoading ? "Checking" : health.data?.status ?? "Offline"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">Documents</span>
              <FileText className="h-5 w-5 text-slate-400" />
            </div>
            <p className="mt-4 text-2xl font-semibold">{stats.data?.total_documents ?? "-"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">Success rate</span>
              <CheckCircle2 className="h-5 w-5 text-slate-400" />
            </div>
            <p className="mt-4 text-2xl font-semibold">{stats.data ? percent(stats.data.parse_success_rate) : "-"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">Failed</span>
              <AlertTriangle className="h-5 w-5 text-slate-400" />
            </div>
            <p className="mt-4 text-2xl font-semibold text-red-600">{stats.data?.failed_documents ?? "-"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">Last 7 days</span>
              <Clock className="h-5 w-5 text-slate-400" />
            </div>
            <p className="mt-4 text-2xl font-semibold">{stats.data?.recent_7_days_documents ?? "-"}</p>
          </CardContent>
        </Card>
      </section>

      {stats.isLoading ? <Skeleton className="h-48 w-full" /> : null}

      {stats.data ? (
        <section className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="border-b border-slate-200 pb-4">
              <div className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-blue-600" />
                <h2 className="font-semibold">Status Distribution</h2>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 p-5">
              {stats.data.status_distribution.map((item) => (
                <div key={item.status}>
                  <div className="mb-1 flex justify-between text-sm">
                    <span className="capitalize text-slate-600">{item.status}</span>
                    <span className="font-medium">{item.count}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full bg-blue-600"
                      style={{ width: `${stats.data.total_documents ? (item.count / stats.data.total_documents) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="border-b border-slate-200 pb-4">
              <div className="flex items-center gap-2">
                <PieChart className="h-5 w-5 text-blue-600" />
                <h2 className="font-semibold">File Types</h2>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 p-5">
              {stats.data.file_type_distribution.map((item) => (
                <div key={item.file_type}>
                  <div className="mb-1 flex justify-between text-sm">
                    <span className="capitalize text-slate-600">{item.file_type}</span>
                    <span className="font-medium">{item.count} · {percent(item.ratio)}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div className="h-2 rounded-full bg-emerald-600" style={{ width: `${item.ratio * 100}%` }} />
                  </div>
                </div>
              ))}
              {!stats.data.file_type_distribution.length ? (
                <p className="text-sm text-slate-500">No documents yet.</p>
              ) : null}
            </CardContent>
          </Card>
        </section>
      ) : null}
    </div>
  );
}
