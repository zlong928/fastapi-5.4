import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileText, Library, Search, Server, UploadCloud } from "lucide-react";
import { Link } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getStatistics, healthCheck } from "@/lib/api";

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function DashboardPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: healthCheck, refetchInterval: 10_000 });
  const stats = useQuery({ queryKey: ["statistics"], queryFn: getStatistics, refetchInterval: 15_000 });

  const quickStats = [
    { label: "文档", value: stats.data?.total_documents ?? "-", icon: FileText },
    { label: "成功率", value: stats.data ? percent(stats.data.parse_success_rate) : "-", icon: CheckCircle2 },
    { label: "失败", value: stats.data?.failed_documents ?? "-", icon: AlertTriangle, danger: true },
    { label: "7 天", value: stats.data?.recent_7_days_documents ?? "-", icon: UploadCloud }
  ];

  const entries = [
    { title: "知识库", href: "/knowledge", icon: Library, meta: `${stats.data?.total_documents ?? 0} 个文档` },
    { title: "搜索", href: "/search", icon: Search, meta: "文档 / 片段" },
    { title: "上传", href: "/knowledge?upload=1", icon: UploadCloud, meta: "PDF / EPUB / Markdown" }
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <section className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">首页</h1>
          <div className="mt-2 flex items-center gap-2 text-sm text-slate-500">
            <Server className="h-4 w-4" />
            <span className={health.isError ? "text-red-500" : "text-emerald-600"}>
              {health.isLoading ? "检查中" : health.data?.status ?? "离线"}
            </span>
          </div>
        </div>
        <Button asChild className="rounded-full bg-slate-950 px-5 text-white hover:bg-slate-800">
          <Link to="/knowledge?upload=1">
            <UploadCloud className="h-4 w-4" />
            上传
          </Link>
        </Button>
      </section>

      {stats.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{stats.error.message}</AlertDescription>
        </Alert>
      ) : null}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {quickStats.map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="rounded-3xl border border-slate-100 bg-white p-4">
              <div className="flex items-center justify-between text-sm text-slate-400">
                <span>{item.label}</span>
                <Icon className="h-4 w-4" />
              </div>
              <p className={`mt-3 text-2xl font-semibold ${item.danger ? "text-red-500" : "text-slate-950"}`}>{item.value}</p>
            </div>
          );
        })}
      </section>

      {stats.isLoading ? <Skeleton className="h-28 w-full rounded-3xl" /> : null}

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="rounded-3xl border border-slate-100 bg-white p-3">
          <div className="mb-2 px-1 text-sm font-semibold text-slate-700">入口</div>
          <div className="space-y-2">
            {entries.map((entry) => {
              const Icon = entry.icon;
              return (
                <Link key={entry.href} to={entry.href} className="flex items-center justify-between rounded-2xl px-3 py-3 transition hover:bg-slate-50">
                  <span className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-50 text-slate-500">
                      <Icon className="h-5 w-5" />
                    </span>
                    <span className="font-medium text-slate-900">{entry.title}</span>
                  </span>
                  <span className="text-sm text-slate-400">{entry.meta}</span>
                </Link>
              );
            })}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-100 bg-white p-4">
          <p className="text-sm font-semibold text-slate-700">解析状态</p>
          <div className="mt-4 space-y-3">
            {stats.data?.status_distribution.map((item) => (
              <div key={item.status}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="text-slate-500">{item.status}</span>
                  <span className="font-medium text-slate-800">{item.count}</span>
                </div>
                <div className="h-2 rounded-full bg-slate-100">
                  <div className="h-2 rounded-full bg-slate-900" style={{ width: `${stats.data.total_documents ? (item.count / stats.data.total_documents) * 100 : 0}%` }} />
                </div>
              </div>
            ))}
            {!stats.data?.status_distribution.length ? <p className="text-sm text-slate-400">暂无数据</p> : null}
          </div>
        </div>
      </section>
    </div>
  );
}
