import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Braces, CheckCircle2, FileText, Image, Loader2, RefreshCw, RotateCw, Table2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getPaper, getPaperAssetBlob, getStructuredExtraction, retryExtraction } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { PaperFigureAssetItem, StructuredExtractionResponse, StructuredFigureResult, StructuredTableResult, StructuredTextResult } from "@/lib/types";
import { ExtractionStatusBadge, fieldLabel, isExtractionBusy, shouldPollPaper } from "@/pages/paperShared";

/* ─── Helpers ─── */

function confidenceColor(c?: string | null) {
  if (c === "high") return "text-emerald-700 bg-emerald-50 ring-emerald-200";
  if (c === "medium") return "text-amber-700 bg-amber-50 ring-amber-200";
  if (c === "low") return "text-red-600 bg-red-50 ring-red-200";
  return "text-slate-500 bg-slate-50 ring-slate-200";
}

function ConfidenceBadge({ confidence }: { confidence?: string | null }) {
  if (!confidence) return null;
  const labels: Record<string, string> = { high: "高置信", medium: "中置信", low: "低置信" };
  return <Badge variant="outline" className={`border-transparent ring-1 text-[10px] ${confidenceColor(confidence)}`}>{labels[confidence] ?? confidence}</Badge>;
}

/* ─── Image Preview ─── */

function FigureImage({ imageUrl }: { imageUrl?: string | null }) {
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSrc(""); setFailed(false);
    if (!imageUrl) return () => {};
    getPaperAssetBlob(imageUrl).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setSrc(objectUrl);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [imageUrl]);

  if (!imageUrl || failed) return <div className="flex aspect-[4/3] items-center justify-center rounded-lg bg-slate-100 text-xs text-slate-400"><Image className="mr-1 h-4 w-4" />无法预览</div>;
  if (!src) return <div className="flex aspect-[4/3] items-center justify-center rounded-lg bg-slate-100 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /></div>;
  return <img src={src} alt="" className="aspect-[4/3] w-full rounded-lg bg-slate-100 object-contain" />;
}

/* ─── Summary Cards ─── */

function SummaryBar({ data }: { data: StructuredExtractionResponse }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      <SummaryCard icon={Image} label="图片分析" value={s.figures_analyzed} color="text-blue-600" />
      <SummaryCard icon={Table2} label="表格分析" value={s.tables_analyzed} color="text-emerald-600" />
      <SummaryCard icon={FileText} label="正文提取" value={s.text_items_extracted} color="text-slate-600" />
      <SummaryCard icon={CheckCircle2} label="总结果" value={s.total_results} color="text-slate-900" />
      <SummaryCard icon={XCircle} label="未找到" value={s.failed_items} color="text-red-500" />
    </div>
  );
}

function SummaryCard({ icon: Icon, label, value, color }: { icon: typeof FileText; label: string; value: number; color: string }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-3 shadow-sm">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500"><Icon className={`h-3.5 w-3.5 ${color}`} />{label}</div>
      <p className="mt-1.5 text-xl font-bold text-slate-900">{value}</p>
    </div>
  );
}

/* ─── Figure Result Card ─── */

function FigureResultCard({ item }: { item: StructuredFigureResult }) {
  return (
    <article className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <FigureImage imageUrl={item.image_url} />
      <div className="space-y-2.5 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[11px] font-medium text-blue-600">{item.figure_id}</p>
            <h3 className="mt-0.5 text-sm font-semibold text-slate-900">{fieldLabel(item.metric)}</h3>
          </div>
          <ConfidenceBadge confidence={item.confidence} />
        </div>
        {item.caption ? <p className="text-xs leading-5 text-slate-500">{item.caption}</p> : null}
        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{item.value}</p>
        {item.evidence ? (
          <div className="rounded-lg bg-slate-50 p-2.5">
            <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">证据来源</p>
            <p className="line-clamp-3 text-xs leading-5 text-slate-600">{item.evidence}</p>
          </div>
        ) : null}
        {item.notes ? <p className="text-xs italic text-slate-500">{item.notes}</p> : null}
      </div>
    </article>
  );
}

/* ─── Table Result Card ─── */

function TableResultCard({ item }: { item: StructuredTableResult }) {
  const hasStructured = Boolean(item.structured_data);
  let rows: string[][] = [];
  if (hasStructured) {
    try { const p = JSON.parse(item.structured_data!); if (Array.isArray(p) && p.length >= 2) rows = p; } catch {}
  }
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-2.5">
      <div className="flex items-start justify-between gap-2">
        <div>
          {item.table_id ? <p className="text-[11px] font-medium text-emerald-600">{item.table_id}</p> : null}
          <h3 className="text-sm font-semibold text-slate-900">{fieldLabel(item.metric)}</h3>
        </div>
        <div className="flex gap-1">
          {item.parse_status === "success" ? <Badge variant="outline" className="border-transparent bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 text-[10px]">结构化</Badge> : null}
          {item.parse_status === "partial" ? <Badge variant="outline" className="border-transparent bg-amber-50 text-amber-700 ring-1 ring-amber-200 text-[10px]">部分解析</Badge> : null}
          {item.parse_status === "failed" ? <Badge variant="outline" className="border-transparent bg-red-50 text-red-600 ring-1 ring-red-200 text-[10px]">解析失败</Badge> : null}
        </div>
      </div>
      {rows.length >= 2 ? (
        <div className="overflow-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-50"><tr>{rows[0].map((h, i) => <th key={i} className="px-2.5 py-1.5 text-left font-medium text-slate-600">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">{rows.slice(1, 8).map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci} className="px-2.5 py-1.5 text-slate-700">{cell}</td>)}</tr>)}</tbody>
          </table>
          {rows.length > 8 ? <p className="px-2.5 py-1 text-[10px] text-slate-400">共 {rows.length - 1} 行</p> : null}
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{item.value}</p>
      )}
      {item.evidence ? (
        <div className="rounded-lg bg-slate-50 p-2.5">
          <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">证据来源</p>
          <p className="line-clamp-3 text-xs leading-5 text-slate-600">{item.evidence}</p>
        </div>
      ) : null}
      {item.notes ? <p className="text-xs italic text-slate-500">{item.notes}</p> : null}
    </article>
  );
}

/* ─── Text Result Card ─── */

function TextResultCard({ item }: { item: StructuredTextResult }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-2">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{fieldLabel(item.metric)}</h3>
        <ConfidenceBadge confidence={item.confidence} />
      </div>
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{item.value}</p>
      {item.evidence ? (
        <div className="rounded-lg bg-slate-50 p-2.5">
          <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">原文证据</p>
          <p className="line-clamp-4 text-xs leading-5 text-slate-600">{item.evidence}</p>
        </div>
      ) : null}
    </article>
  );
}

/* ─── Result Body ─── */

function PaperFiguresGallery({ figures }: { figures: PaperFigureAssetItem[] }) {
  if (!figures.length) return null;
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Image className="h-4 w-4 text-indigo-500" />
        <h2 className="text-sm font-semibold text-slate-900">论文图片</h2>
        <Badge variant="outline" className="text-[10px]">{figures.length}</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {figures.map((fig) => (
          <article key={fig.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <FigureImage imageUrl={fig.image_url} />
            <div className="p-2.5">
              <p className="truncate text-xs font-medium text-slate-900">{fig.figure_label}</p>
              <p className="mt-0.5 text-[10px] text-slate-400">page {fig.page ?? "-"} · {fig.source || fig.asset_type}</p>
              {fig.caption ? <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{fig.caption}</p> : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ResultBody({ data }: { data: StructuredExtractionResponse }) {
  const [showRaw, setShowRaw] = useState(false);
  const hasFigures = data.figure_results.length > 0;
  const hasTables = data.table_results.length > 0;
  const hasText = data.text_results.length > 0;
  const hasPaperFigures = (data.paper_figures ?? []).length > 0;

  return (
    <div className="space-y-6">
      <SummaryBar data={data} />

      {hasPaperFigures ? <PaperFiguresGallery figures={data.paper_figures} /> : null}

      {hasFigures ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Image className="h-4 w-4 text-blue-500" />
            <h2 className="text-sm font-semibold text-slate-900">图片/图表分析结果</h2>
            <Badge variant="outline" className="text-[10px]">{data.figure_results.length}</Badge>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.figure_results.map((item, i) => <FigureResultCard key={i} item={item} />)}
          </div>
        </section>
      ) : null}

      {hasTables ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Table2 className="h-4 w-4 text-emerald-500" />
            <h2 className="text-sm font-semibold text-slate-900">表格数据</h2>
            <Badge variant="outline" className="text-[10px]">{data.table_results.length}</Badge>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.table_results.map((item, i) => <TableResultCard key={i} item={item} />)}
          </div>
        </section>
      ) : null}

      {hasText ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <FileText className="h-4 w-4 text-slate-500" />
            <h2 className="text-sm font-semibold text-slate-900">正文提取</h2>
            <Badge variant="outline" className="text-[10px]">{data.text_results.length}</Badge>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.text_results.map((item, i) => <TextResultCard key={i} item={item} />)}
          </div>
        </section>
      ) : null}

      {data.not_found.length > 0 ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h2 className="text-sm font-semibold text-slate-900">未找到的信息</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {data.not_found.map((item, i) => (
              <Badge key={i} variant="outline" className="border-amber-200 bg-amber-50 text-amber-700">{fieldLabel(item)}</Badge>
            ))}
          </div>
        </section>
      ) : null}

      <div className="pt-2">
        <Button variant="ghost" size="sm" className="text-xs text-slate-400" onClick={() => setShowRaw(!showRaw)}>
          <Braces className="mr-1 h-3.5 w-3.5" />{showRaw ? "收起" : "查看"} 原始 JSON
        </Button>
        {showRaw && <pre className="mt-2 max-h-96 overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(data, null, 2)}</pre>}
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

export function PaperExtractionResultPage() {
  const paperId = Number(useParams().id);
  const [searchParams] = useSearchParams();
  const selectedJobId = Number(searchParams.get("job"));
  const hasSelectedJob = Number.isFinite(selectedJobId) && selectedJobId > 0;
  const queryClient = useQueryClient();

  const paperQuery = useQuery({ queryKey: ["paper", paperId], queryFn: () => getPaper(paperId), enabled: Number.isFinite(paperId), refetchInterval: (q) => shouldPollPaper(q.state.data) ? 2000 : false });
  const structuredQuery = useQuery({
    queryKey: ["extraction-structured", selectedJobId],
    queryFn: () => getStructuredExtraction(selectedJobId),
    enabled: hasSelectedJob,
    refetchInterval: (q) => isExtractionBusy(q.state.data?.status) ? 2000 : false,
  });
  const retryMutation = useMutation({ mutationFn: (id: number) => retryExtraction(id), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["paper", paperId] }); queryClient.invalidateQueries({ queryKey: ["extraction-structured", selectedJobId] }); } });

  const paper = paperQuery.data;
  const data = structuredQuery.data;
  const loading = paperQuery.isLoading || (hasSelectedJob && structuredQuery.isLoading);

  if (loading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  return (
    <main className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 px-2 text-slate-500">
            <Link to={`/papers/${paperId}/extraction`}><ArrowLeft className="h-4 w-4" />提取任务</Link>
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            {data && <ExtractionStatusBadge status={data.status} />}
            {data && <span className="text-xs text-slate-400">#{selectedJobId} · {formatChinaDateTime(data.updated_at)}</span>}
          </div>
          <h1 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">{paper.title}</h1>
          {data && <p className="mt-1 max-w-2xl text-sm text-slate-500">{data.task}</p>}
        </div>
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm"><Link to={`/papers/${paper.id}`}><FileText className="h-4 w-4" />论文</Link></Button>
          <Button variant="outline" size="sm" onClick={() => { paperQuery.refetch(); structuredQuery.refetch(); }} disabled={structuredQuery.isFetching}>
            {structuredQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </Button>
        </div>
      </header>

      {!data && !hasSelectedJob && (
        <section className="rounded-xl border border-slate-200 bg-white p-10 text-center">
          <p className="text-sm text-slate-500">暂无提取结果</p>
          <Button asChild className="mt-4 rounded-xl"><Link to={`/papers/${paperId}/extraction`}>创建提取任务</Link></Button>
        </section>
      )}

      {data && isExtractionBusy(data.status) && (
        <section className="rounded-xl border border-slate-200 bg-white p-10 text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-slate-400" />
          <p className="mt-3 text-sm text-slate-600">提取任务执行中...</p>
        </section>
      )}

      {data?.status === "failed" && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>{data.error_message ?? "提取失败"}</span>
            <Button size="sm" variant="outline" className="border-red-200 text-red-700" onClick={() => retryMutation.mutate(selectedJobId)} disabled={retryMutation.isPending}>
              {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}重试
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {data?.status === "done" && <ResultBody data={data} />}
    </main>
  );
}
