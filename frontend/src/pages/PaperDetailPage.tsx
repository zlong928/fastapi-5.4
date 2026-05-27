import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Loader2, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getPaper, getPaperAssetBlob, parsePaper, retryExtraction, runExtraction } from "@/lib/api";
import { ExtractionResult, PaperDetail, PaperFigure, PaperTable } from "@/lib/types";
import { cn } from "@/lib/utils";

const DEFAULT_QUERY = "提取材料组成、实验分组、关键指标和主要结论";
const FIELD_LABELS: Record<string, string> = { materials: "材料组成", experiment_groups: "实验分组", key_metrics: "关键指标", conclusion: "主要结论" };
const STATUS_LABELS: Record<string, string> = { uploaded: "已上传", parsing: "解析中", parsed: "已解析", extracting: "提取中", done: "已完成", failed: "失败" };

function isBusy(status?: string) {
  return status === "parsing" || status === "extracting";
}

function FigureImage({ figure, active, onOpen }: { figure: PaperFigure; active?: boolean; onOpen: (src: string) => void }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let objectUrl = "";
    let cancelled = false;
    getPaperAssetBlob(figure.image_path)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => setSrc(""));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [figure.image_path]);

  if (!src) return <div className="flex aspect-[4/3] items-center justify-center rounded-2xl bg-slate-50 text-sm text-slate-400">图片加载中</div>;
  return (
    <button type="button" onClick={() => onOpen(src)} className={cn("group relative block w-full rounded-2xl text-left ring-offset-2 transition hover:ring-2 hover:ring-slate-300", active && "ring-2 ring-blue-300")}>
      <img src={src} alt={figure.figure_label} className="aspect-[4/3] w-full rounded-2xl bg-slate-50 object-contain" />
      <span className="absolute right-2 top-2 hidden rounded-full bg-white/90 p-1.5 text-slate-600 shadow-sm group-hover:block"><Eye className="h-4 w-4" /></span>
    </button>
  );
}

function ResultGroup({ title, results, onSourceClick }: { title: string; results: ExtractionResult[]; onSourceClick: (result: ExtractionResult) => void }) {
  return (
    <section className="rounded-3xl border border-slate-100 bg-white p-4">
      <h3 className="mb-3 text-sm font-medium text-slate-700">{title}</h3>
      <div className="space-y-2">
        {results.length ? results.map((result) => (
          <button key={result.id} type="button" onClick={() => onSourceClick(result)} className="block w-full rounded-2xl bg-slate-50 p-3 text-left transition hover:bg-slate-100">
            <div className="mb-1 flex flex-wrap gap-2 text-xs text-slate-400">
              <span>{FIELD_LABELS[result.field_name] ?? result.field_name}</span>
              <span>{result.source_type}</span>
              {result.source_id ? <span>#{result.source_id}</span> : null}
              {result.confidence !== null && result.confidence !== undefined ? <span>{Math.round(result.confidence * 100)}%</span> : null}
            </div>
            <p className="text-sm leading-6 text-slate-700">{result.content}</p>
            {result.evidence ? <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-500">证据：{result.evidence}</p> : null}
          </button>
        )) : <div className="rounded-2xl bg-slate-50 p-6 text-center text-sm text-slate-400">暂无结果</div>}
      </div>
    </section>
  );
}

function TableCard({ table, active }: { table: PaperTable; active?: boolean }) {
  return (
    <div id={`table-${table.id}`} className={cn("mb-3 rounded-2xl bg-slate-50 p-3 transition", active && "ring-2 ring-blue-300")}>
      <p className="mb-2 text-sm font-medium text-slate-700">{table.table_label} · page {table.page ?? "-"}</p>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-sm leading-6 text-slate-600">{table.content}</pre>
    </div>
  );
}

export function PaperDetailPage() {
  const paperId = Number(useParams().id);
  const queryClient = useQueryClient();
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [activeFigureId, setActiveFigureId] = useState<number | null>(null);
  const [activeTableId, setActiveTableId] = useState<number | null>(null);
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  const paperQuery = useQuery({
    queryKey: ["paper", paperId],
    queryFn: () => getPaper(paperId),
    enabled: Number.isFinite(paperId),
    refetchInterval: (queryState) => isBusy(queryState.state.data?.status) ? 2000 : false
  });
  const paper = paperQuery.data;
  const parseMutation = useMutation({ mutationFn: parsePaper, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["paper", paperId] }) });
  const runMutation = useMutation({ mutationFn: () => runExtraction(paperId, query), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["paper", paperId] }) });
  const retryMutation = useMutation({ mutationFn: (jobId: number) => retryExtraction(jobId), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["paper", paperId] }) });

  const grouped = useMemo(() => {
    const results = paper?.latest_extraction_job?.results ?? [];
    return {
      text: results.filter((item) => item.source_type === "text"),
      figure: results.filter((item) => item.source_type === "figure"),
      table: results.filter((item) => item.source_type === "table")
    };
  }, [paper?.latest_extraction_job?.results]);

  function focusSource(result: ExtractionResult) {
    if (result.source_type === "figure" && result.source_id) {
      setActiveFigureId(result.source_id);
      window.document.getElementById(`figure-${result.source_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (result.source_type === "table" && result.source_id) {
      setActiveTableId(result.source_id);
      window.document.getElementById(`table-${result.source_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  if (paperQuery.isLoading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  const error = paper.parse_error || paper.latest_extraction_job?.error_message;
  const canExtract = paper.status === "parsed" || paper.status === "done" || paper.figures.length > 0 || paper.tables.length > 0;
  const busy = parseMutation.isPending || runMutation.isPending || retryMutation.isPending || isBusy(paper.status);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <div className="rounded-3xl border border-slate-100 bg-white p-5">
        <Button asChild variant="ghost" size="sm" className="mb-2 rounded-xl px-2"><Link to="/papers">论文列表</Link></Button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{paper.title}</h1>
            <p className="mt-1 text-sm text-slate-400">状态：{STATUS_LABELS[paper.status] ?? paper.status}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="rounded-xl border-slate-100 shadow-none" onClick={() => parseMutation.mutate(paper.id)} disabled={busy}>
              {parseMutation.isPending || paper.status === "parsing" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}解析论文
            </Button>
            <Button className="rounded-xl" onClick={() => runMutation.mutate()} disabled={busy || !canExtract || !query.trim()}>
              {runMutation.isPending || paper.status === "extracting" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}开始提取
            </Button>
            <Button variant="outline" className="rounded-xl border-slate-100 shadow-none" onClick={() => paperQuery.refetch()} disabled={paperQuery.isFetching}>
              {paperQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}刷新
            </Button>
          </div>
        </div>
        {error ? <Alert variant="destructive" className="mt-4 rounded-2xl"><AlertDescription>{error}</AlertDescription></Alert> : null}
        <textarea value={query} onChange={(event) => setQuery(event.target.value)} className="mt-4 min-h-20 w-full rounded-2xl border border-slate-100 p-3 text-sm focus:outline-none focus:ring-2 focus:ring-slate-200" />
        {paper.latest_extraction_job?.status === "failed" ? (
          <Button className="mt-3 rounded-xl" variant="outline" onClick={() => retryMutation.mutate(paper.latest_extraction_job!.id)} disabled={retryMutation.isPending}>
            {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}重试提取
          </Button>
        ) : null}
      </div>

      <section className="rounded-3xl border border-slate-100 bg-white p-4">
        <h2 className="mb-3 text-sm font-medium text-slate-700">正文预览</h2>
        <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded-2xl bg-slate-50 p-4 text-sm leading-7 text-slate-700">{(paper.text_content || "暂无正文").slice(0, 2000)}</pre>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-3xl border border-slate-100 bg-white p-4">
          <h2 className="mb-3 text-sm font-medium text-slate-700">图片区域</h2>
          {paper.figures.map((figure) => (
            <div id={`figure-${figure.id}`} key={figure.id} className="mb-3 scroll-mt-20">
              <FigureImage figure={figure} active={activeFigureId === figure.id} onOpen={setPreviewImage} />
              <p className="mt-2 text-sm text-slate-600">{figure.figure_label} · page {figure.page ?? "-"} · {figure.caption}</p>
            </div>
          ))}
          {!paper.figures.length ? <div className="rounded-2xl bg-slate-50 p-8 text-center text-sm text-slate-400">暂无图片</div> : null}
        </section>
        <section className="rounded-3xl border border-slate-100 bg-white p-4">
          <h2 className="mb-3 text-sm font-medium text-slate-700">表格区域</h2>
          {paper.tables.map((table) => <TableCard key={table.id} table={table} active={activeTableId === table.id} />)}
          {!paper.tables.length ? <div className="rounded-2xl bg-slate-50 p-8 text-center text-sm text-slate-400">暂无表格</div> : null}
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <ResultGroup title="正文结果" results={grouped.text} onSourceClick={focusSource} />
        <ResultGroup title="图片结果" results={grouped.figure} onSourceClick={focusSource} />
        <ResultGroup title="表格结果" results={grouped.table} onSourceClick={focusSource} />
      </div>

      {previewImage ? <ImageModal src={previewImage} paper={paper} onClose={() => setPreviewImage(null)} /> : null}
    </div>
  );
}

function ImageModal({ src, paper, onClose }: { src: string; paper: PaperDetail; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 p-4 text-white">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="truncate text-sm font-medium">{paper.title}</p>
        <Button type="button" variant="ghost" size="sm" className="text-white hover:bg-white/10 hover:text-white" onClick={onClose}><X className="h-4 w-4" /></Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <img src={src} alt={paper.title} className="mx-auto max-h-full max-w-full object-contain" />
      </div>
    </div>
  );
}
