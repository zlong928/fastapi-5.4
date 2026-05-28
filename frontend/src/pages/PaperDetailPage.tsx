import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, Eye, FileText, Images, Loader2, RefreshCw, Table2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getPaper, getPaperAssetBlob, parsePaper } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { PaperDetail, PaperFigure, PaperTable } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PaperStatusBadge, canExtractPaper, shouldPollPaper } from "@/pages/paperShared";

const TABLE_STATUS_LABELS: Record<string, string> = {
  success: "success",
  fallback: "fallback",
  partial: "partial"
};

function tableStatusClass(status?: string | null) {
  if (status === "success") return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (status === "fallback") return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
  return "bg-slate-100 text-slate-600";
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

  if (!src) return <div className="flex aspect-[4/3] items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-400">图片加载中</div>;
  return (
    <button type="button" onClick={() => onOpen(src)} className={cn("group relative block w-full rounded-xl text-left ring-offset-2 transition hover:ring-2 hover:ring-slate-300", active && "ring-2 ring-blue-300")}>
      <img src={src} alt={figure.figure_label} className="aspect-[4/3] w-full rounded-xl bg-slate-50 object-contain" />
      <span className="absolute right-2 top-2 hidden rounded-full bg-white/90 p-1.5 text-slate-600 shadow-sm group-hover:block"><Eye className="h-4 w-4" /></span>
    </button>
  );
}

function TableCandidate({ table }: { table: PaperTable }) {
  const parseStatus = table.parse_status ?? "partial";
  return (
    <article id={`table-${table.id}`} className="scroll-mt-20 rounded-xl bg-slate-50 p-3">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-700">{table.table_label}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>page {table.page ?? "-"}</span>
            <span>{table.source ?? "text candidate"}</span>
          </div>
        </div>
        <Badge variant="outline" className={cn("border-transparent", tableStatusClass(parseStatus))}>
          {TABLE_STATUS_LABELS[parseStatus] ?? parseStatus}
        </Badge>
      </div>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-sm leading-6 text-slate-600">{table.content}</pre>
    </article>
  );
}

export function PaperDetailPage() {
  const paperId = Number(useParams().id);
  const queryClient = useQueryClient();
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  const paperQuery = useQuery({
    queryKey: ["paper", paperId],
    queryFn: () => getPaper(paperId),
    enabled: Number.isFinite(paperId),
    refetchInterval: (queryState) => shouldPollPaper(queryState.state.data) ? 2000 : false
  });
  const paper = paperQuery.data;
  const parseMutation = useMutation({
    mutationFn: () => parsePaper(paperId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["paper", paperId] })
  });

  if (paperQuery.isLoading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  const latestJob = paper.latest_extraction_job;
  const latestDoneJob = latestJob?.status === "done" ? latestJob : null;
  const busy = parseMutation.isPending || paper.status === "processing" || paper.status === "parsing";

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
        <Button asChild variant="ghost" size="sm" className="mb-3 rounded-xl px-2 text-slate-500">
          <Link to="/papers"><ArrowLeft className="h-4 w-4" />论文列表</Link>
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <PaperStatusBadge status={paper.status} />
              <span className="text-xs text-slate-400">更新：{formatChinaDateTime(paper.updated_at)}</span>
            </div>
            <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight text-slate-950">{paper.title}</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="rounded-xl border-slate-200 shadow-none" onClick={() => parseMutation.mutate()} disabled={busy}>
              {parseMutation.isPending || paper.status === "parsing" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              解析论文
            </Button>
            {canExtractPaper(paper) ? (
              <Button asChild className="rounded-xl">
                <Link to={`/papers/${paper.id}/extraction`}><BarChart3 className="h-4 w-4" />提取任务</Link>
              </Button>
            ) : (
              <Button className="rounded-xl" disabled><BarChart3 className="h-4 w-4" />提取任务</Button>
            )}
            <Button asChild variant="outline" className="rounded-xl border-slate-200 shadow-none">
              <Link to={`/papers/${paper.id}/results${latestDoneJob ? `?job=${latestDoneJob.id}` : ""}`}>提取结果</Link>
            </Button>
          </div>
        </div>

        {paper.parse_error ? (
          <Alert variant="destructive" className="mt-4 rounded-xl">
            <AlertDescription>{paper.parse_error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl bg-slate-50 p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500"><FileText className="h-4 w-4" />正文字符</div>
            <p className="mt-2 text-2xl font-semibold text-slate-950">{paper.text_content?.length ?? 0}</p>
          </div>
          <div className="rounded-2xl bg-slate-50 p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500"><Images className="h-4 w-4" />图片</div>
            <p className="mt-2 text-2xl font-semibold text-slate-950">{paper.figures.length}</p>
          </div>
          <div className="rounded-2xl bg-slate-50 p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500"><Table2 className="h-4 w-4" />表格候选</div>
            <p className="mt-2 text-2xl font-semibold text-slate-950">{paper.tables.length}</p>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-800">正文预览</h2>
        <pre className="max-h-[420px] overflow-y-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-4 font-mono text-sm leading-7 text-slate-700">{(paper.text_content || "暂无正文").slice(0, 4200)}</pre>
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.85fr)]">
        <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-800">图片区域</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {paper.figures.map((figure) => (
              <article id={`figure-${figure.id}`} key={figure.id} className="scroll-mt-20 rounded-xl border border-slate-100 p-3">
                <FigureImage figure={figure} onOpen={setPreviewImage} />
                <div className="mt-3 flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-700">{figure.figure_label}</p>
                    <p className="mt-1 text-xs text-slate-500">page {figure.page ?? "-"}</p>
                  </div>
                  {figure.source === "fallback_snapshot" ? (
                    <Badge variant="outline" className="border-transparent bg-amber-50 text-amber-700 ring-1 ring-amber-200">Fallback Snapshot</Badge>
                  ) : null}
                </div>
                <dl className="mt-2 space-y-1 text-xs leading-5 text-slate-500">
                  <div>
                    <dt className="inline font-medium text-slate-600">caption: </dt>
                    <dd className="inline break-words">{figure.caption || "无图注"}</dd>
                  </div>
                  <div>
                    <dt className="inline font-medium text-slate-600">source: </dt>
                    <dd className="inline break-words">{figure.source || "extracted_image"}</dd>
                  </div>
                  {figure.notes ? (
                    <div>
                      <dt className="inline font-medium text-slate-600">notes: </dt>
                      <dd className="inline break-words">{figure.notes}</dd>
                    </div>
                  ) : null}
                </dl>
              </article>
            ))}
          </div>
          {!paper.figures.length ? <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-400">暂无图片</div> : null}
        </section>

        <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-800">表格区域</h2>
          <div className="space-y-3">
            {paper.tables.map((table) => <TableCandidate key={table.id} table={table} />)}
          </div>
          {!paper.tables.length ? <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-400">暂无表格</div> : null}
        </section>
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
