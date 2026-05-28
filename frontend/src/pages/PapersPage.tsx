import { useQuery } from "@tanstack/react-query";
import { Eye, FileText, Loader2, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { getPapers } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { PaperStatusBadge, paperStatusLabel } from "@/pages/paperShared";

export function PapersPage() {
  const [keyword, setKeyword] = useState("");
  const papersQuery = useQuery({ queryKey: ["papers"], queryFn: getPapers });

  const papers = papersQuery.data ?? [];
  const filteredPapers = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return papers;
    return papers.filter((paper) => paper.title.toLowerCase().includes(q) || paperStatusLabel(paper.status).includes(q));
  }, [keyword, papers]);

  const stats = useMemo(() => {
    const done = papers.filter((paper) => paper.status === "done" || paper.status === "completed" || paper.status === "parsed").length;
    const failed = papers.filter((paper) => paper.status === "failed").length;
    return { total: papers.length, done, failed };
  }, [papers]);

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-500">论文列表</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">PDF 论文</h1>
          </div>
          <Button asChild className="rounded-xl">
            <Link to="/papers/upload"><Plus className="h-4 w-4" />上传论文</Link>
          </Button>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">全部</p>
            <p className="mt-2 text-2xl font-semibold text-slate-950">{stats.total}</p>
          </div>
          <div className="rounded-2xl bg-emerald-50 p-4">
            <p className="text-xs font-medium text-emerald-700">已完成</p>
            <p className="mt-2 text-2xl font-semibold text-emerald-950">{stats.done}</p>
          </div>
          <div className="rounded-2xl bg-red-50 p-4">
            <p className="text-xs font-medium text-red-700">失败</p>
            <p className="mt-2 text-2xl font-semibold text-red-950">{stats.failed}</p>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="relative min-w-64 flex-1 sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索标题或状态"
              className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none transition focus:ring-2 focus:ring-slate-200"
            />
          </div>
          {papersQuery.isFetching ? <span className="inline-flex items-center gap-2 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />刷新中</span> : null}
        </div>

        <div className="overflow-hidden rounded-xl border border-slate-100">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-medium text-slate-500">
              <tr>
                <th className="px-4 py-3">标题</th>
                <th className="px-4 py-3">状态</th>
                <th className="hidden px-4 py-3 md:table-cell">创建时间</th>
                <th className="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredPapers.map((paper) => (
                <tr key={paper.id} className="border-t border-slate-100 align-top">
                  <td className="max-w-[520px] px-4 py-3">
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                        <FileText className="h-4 w-4" />
                      </span>
                      <div className="min-w-0">
                        <Link to={`/papers/${paper.id}`} className="line-clamp-2 font-medium text-slate-900 hover:text-slate-600">{paper.title}</Link>
                        <p className="mt-1 text-xs text-slate-400">更新：{formatChinaDateTime(paper.updated_at)}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3"><PaperStatusBadge status={paper.status} /></td>
                  <td className="hidden px-4 py-3 text-slate-500 md:table-cell">{formatChinaDateTime(paper.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <Button asChild size="sm" variant="outline" className="rounded-xl border-slate-200 shadow-none">
                      <Link to={`/papers/${paper.id}`}><Eye className="h-4 w-4" />详情</Link>
                    </Button>
                  </td>
                </tr>
              ))}
              {!papersQuery.isLoading && !filteredPapers.length ? (
                <tr>
                  <td colSpan={4} className="px-4 py-12 text-center text-sm text-slate-400">暂无论文</td>
                </tr>
              ) : null}
              {papersQuery.isLoading ? (
                <tr>
                  <td colSpan={4} className="px-4 py-12 text-center text-sm text-slate-400">加载中</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
