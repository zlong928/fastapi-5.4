import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, FileText, PieChart, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { getStatistics } from "@/lib/api";

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function StatisticsPage() {
  const stats = useQuery({ queryKey: ["statistics"], queryFn: getStatistics, refetchInterval: 15_000 });

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-400">Knowledge analytics</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">统计面板</h1>
          <p className="mt-2 text-sm text-slate-500">查看知识库文档数量、解析成功率、失败数和类型分布。</p>
        </div>
        <Button variant="outline" className="rounded-full" onClick={() => stats.refetch()} disabled={stats.isFetching}>
          <RefreshCw className={stats.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
          刷新
        </Button>
      </section>

      {stats.isError ? (
        <div className="rounded-3xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          加载统计失败：{stats.error instanceof Error ? stats.error.message : "未知错误"}
        </div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {[
          { label: "总文档数", value: stats.data?.total_documents ?? "-", icon: FileText },
          { label: "解析成功", value: stats.data?.done_documents ?? "-", icon: CheckCircle2 },
          { label: "失败文档", value: stats.data?.failed_documents ?? "-", icon: AlertTriangle },
          { label: "成功率", value: stats.data ? percent(stats.data.parse_success_rate) : "-", icon: PieChart },
          { label: "近 7 天新增", value: stats.data?.recent_7_days_documents ?? "-", icon: Clock }
        ].map((item) => (
          <Card key={item.label} className="rounded-3xl border-slate-100 shadow-sm">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-500">{item.label}</span>
                <item.icon className="h-5 w-5 text-slate-300" />
              </div>
              <p className="mt-4 text-3xl font-semibold tracking-tight">{item.value}</p>
            </CardContent>
          </Card>
        ))}
      </section>

      {stats.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="h-72 animate-pulse rounded-3xl bg-slate-50" />
          <div className="h-72 animate-pulse rounded-3xl bg-slate-50" />
        </div>
      ) : null}

      {stats.data ? (
        <section className="grid gap-4 lg:grid-cols-2">
          <Card className="rounded-3xl border-slate-100 shadow-sm">
            <CardHeader className="border-b border-slate-100 pb-4">
              <h2 className="font-semibold">状态分布</h2>
            </CardHeader>
            <CardContent className="space-y-4 p-5">
              {stats.data.status_distribution.map((item) => (
                <div key={item.status}>
                  <div className="mb-2 flex justify-between text-sm">
                    <span className="text-slate-600">{item.status}</span>
                    <span className="font-medium">{item.count}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div className="h-2 rounded-full bg-slate-950" style={{ width: `${stats.data.total_documents ? (item.count / stats.data.total_documents) * 100 : 0}%` }} />
                  </div>
                </div>
              ))}
              {!stats.data.status_distribution.length ? <p className="text-sm text-slate-500">暂无状态数据。</p> : null}
            </CardContent>
          </Card>

          <Card className="rounded-3xl border-slate-100 shadow-sm">
            <CardHeader className="border-b border-slate-100 pb-4">
              <h2 className="font-semibold">文件类型分布</h2>
            </CardHeader>
            <CardContent className="space-y-4 p-5">
              {stats.data.file_type_distribution.map((item) => (
                <div key={item.file_type}>
                  <div className="mb-2 flex justify-between text-sm">
                    <span className="text-slate-600">{item.file_type}</span>
                    <span className="font-medium">{item.count} · {percent(item.ratio)}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div className="h-2 rounded-full bg-slate-950" style={{ width: `${item.ratio * 100}%` }} />
                  </div>
                </div>
              ))}
              {!stats.data.file_type_distribution.length ? <p className="text-sm text-slate-500">暂无类型数据。</p> : null}
            </CardContent>
          </Card>
        </section>
      ) : null}
    </div>
  );
}
