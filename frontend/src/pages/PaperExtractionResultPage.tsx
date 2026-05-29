import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Braces, CheckCircle2, FileText, Image, Loader2, MapPin, RefreshCw, RotateCw, Table2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getDocumentAssets, getExtraction, getPaper, getPaperAssetBlob, retryExtraction } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { DocumentAsset, ExtractionJob, ExtractionResult } from "@/lib/types";
import { ExtractionStatusBadge, confidencePercent, fieldLabel, isExtractionBusy, shouldPollPaper } from "@/pages/paperShared";

type EvidenceType = "text" | "table" | "figure" | "chart" | "equation" | "page_region" | "unknown";
type ResultGroup = "visual" | "table" | "text";


function readableContent(content: string) {
  const trimmed = content.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return content;
  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) return parsed.map((row) => (Array.isArray(row) ? row.join(" | ") : String(row))).join("\n");
    if (typeof parsed === "object") return Object.entries(parsed).map(([k, v]) => `${k}: ${v}`).filter(Boolean).join("\n");
    return content;
  } catch {
    return content;
  }
}

function assetMap(assets: DocumentAsset[]) {
  return new Map(assets.map((a) => [a.id, a]));
}

function normalizeEvidenceType(value: unknown): EvidenceType {
  const n = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (["text", "table", "figure", "chart", "equation", "page_region"].includes(n)) return n as EvidenceType;
  if (["image", "visual", "picture"].includes(n)) return "figure";
  return "unknown";
}

function evidenceTypeForResult(r: ExtractionResult, assetsById: Map<number, DocumentAsset>): EvidenceType {
  const explicit = normalizeEvidenceType(r.evidence_type);
  if (explicit !== "unknown") return explicit;
  if (r.source_type === "text" || !r.source_id) return "text";
  const asset = assetsById.get(r.source_id);
  if (asset?.asset_type === "table") return "table";
  if (asset?.asset_type === "figure") return "figure";
  return "unknown";
}

function groupForResult(r: ExtractionResult, assetsById: Map<number, DocumentAsset>): ResultGroup {
  const et = evidenceTypeForResult(r, assetsById);
  if (et === "figure" || et === "chart") return "visual";
  if (et === "table") return "table";
  return "text";
}

function isFallback(r: ExtractionResult) {
  return r.extraction_mode === "fallback_caption_only" || r.extraction_mode === "not_found";
}

function previewPath(r: ExtractionResult, asset?: DocumentAsset) {
  if (r.thumbnail_url) return r.thumbnail_url;
  if (r.image_url) return r.image_url;
  if (asset?.file_path && String(asset.mime_type || "").startsWith("image/")) return `/papers/assets/${asset.id}`;
  return "";
}


function ParseStatusIcon({ status }: { status?: string | null }) {
  if (status === "success") return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-3.5 w-3.5 text-red-400" />;
  if (status === "partial") return <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />;
  return null;
}

function ConfidenceBar({ confidence }: { confidence: number | null }) {
  if (confidence === null) return null;
  const color = confidence >= 70 ? "bg-emerald-500" : confidence >= 40 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${confidence}%` }} />
      </div>
      <span className="text-xs tabular-nums text-slate-500">{confidence}%</span>
    </div>
  );
}

function ModeBadge({ mode }: { mode?: string | null }) {
  if (!mode || mode === "text_extraction" || mode === "visual_analysis") return null;
  if (mode === "fallback_caption_only") return <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-700 text-[10px]">仅图注</Badge>;
  if (mode === "not_found") return <Badge variant="outline" className="border-red-200 bg-red-50 text-red-600 text-[10px]">未找到</Badge>;
  return null;
}

function EvidenceBlock({ evidence, label }: { evidence: string; label?: string }) {
  if (!evidence || evidence.startsWith("无原文证据")) return <p className="mt-2 text-xs italic text-slate-400">{evidence || "无证据"}</p>;
  return (
    <div className="mt-3 rounded-md border border-slate-100 bg-slate-50 p-3">
      <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">{label || "原文证据"}</p>
      <p className="line-clamp-4 text-xs leading-5 text-slate-600">{evidence}</p>
    </div>
  );
}

function StructuredDataTable({ data }: { data: string }) {
  let rows: string[][] = [];
  try {
    const parsed = JSON.parse(data);
    if (Array.isArray(parsed) && parsed.length >= 2) rows = parsed;
  } catch { return null; }
  if (rows.length < 2) return null;
  const headers = rows[0];
  const body = rows.slice(1, 12);
  return (
    <div className="mt-3 overflow-auto rounded-md border border-slate-200">
      <table className="w-full text-xs">
        <thead className="bg-slate-50">
          <tr>{headers.map((h, i) => <th key={i} className="px-3 py-2 text-left font-medium text-slate-600">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {body.map((row, ri) => (
            <tr key={ri} className="hover:bg-slate-50/50">
              {row.map((cell, ci) => <td key={ci} className="px-3 py-1.5 text-slate-700">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 12 && <p className="px-3 py-1.5 text-[10px] text-slate-400">...共 {rows.length - 1} 行</p>}
    </div>
  );
}

function ImagePreview({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  const path = previewPath(result, asset);
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSrc(""); setFailed(false);
    if (!path) return () => {};
    getPaperAssetBlob(path).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setSrc(objectUrl);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path]);

  if (!path || failed) return <div className="flex aspect-[4/3] items-center justify-center rounded-md bg-slate-50 text-xs text-slate-400"><Image className="mr-1 h-4 w-4" />无预览</div>;
  if (!src) return <div className="flex aspect-[4/3] items-center justify-center rounded-md bg-slate-50 text-xs text-slate-400">加载中...</div>;
  return <img src={src} alt={result.caption || result.figure_id || ""} className="aspect-[4/3] w-full rounded-md bg-slate-50 object-contain" />;
}


function VisualResultCard({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  const confidence = confidencePercent(result.confidence);
  return (
    <article className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <ImagePreview result={result} asset={asset} />
      <div className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <ParseStatusIcon status={result.parse_status} />
              <h3 className="truncate text-sm font-semibold text-slate-900">{fieldLabel(result.field_name)}</h3>
              <ModeBadge mode={result.extraction_mode} />
            </div>
            {result.figure_id && <p className="mt-0.5 text-[11px] text-slate-400">{result.figure_id}</p>}
          </div>
        </div>
        <ConfidenceBar confidence={confidence} />
        {result.caption && <p className="text-xs leading-5 text-slate-500">{result.caption}</p>}
        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{readableContent(result.content)}</p>
        {result.structured_data && <StructuredDataTable data={result.structured_data} />}
        <EvidenceBlock evidence={result.evidence} label="图中证据" />
        {result.notes && <p className="mt-2 text-xs italic text-slate-500">{result.notes}</p>}
        <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-slate-400">
          <MapPin className="h-3 w-3" /><span>p.{result.page ?? "-"}</span>
          <span>{result.source || asset?.asset_type || result.source_type}</span>
        </div>
      </div>
    </article>
  );
}

function TableResultCard({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  const confidence = confidencePercent(result.confidence);
  const hasStructured = Boolean(result.structured_data);
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <ParseStatusIcon status={result.parse_status} />
          <h3 className="text-sm font-semibold text-slate-900">{fieldLabel(result.field_name)}</h3>
          <ModeBadge mode={result.extraction_mode} />
          {hasStructured && <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700 text-[10px]">结构化</Badge>}
        </div>
      </div>
      <ConfidenceBar confidence={confidence} />
      {result.caption && <p className="text-xs text-slate-500">{result.caption}</p>}
      {hasStructured ? (
        <StructuredDataTable data={result.structured_data!} />
      ) : (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs leading-5 text-slate-700">
          {asset?.markdown || asset?.text_content || readableContent(result.content)}
        </pre>
      )}
      <EvidenceBlock evidence={result.evidence} label="表格证据" />
      {result.notes && <p className="text-xs italic text-slate-500">{result.notes}</p>}
      <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-slate-400">
        <MapPin className="h-3 w-3" /><span>p.{result.page ?? "-"}</span>
        {result.parse_status && <span>解析: {result.parse_status}</span>}
      </div>
    </article>
  );
}

function TextResultCard({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  const confidence = confidencePercent(result.confidence);
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <ParseStatusIcon status={result.parse_status} />
          <h3 className="text-sm font-semibold text-slate-900">{fieldLabel(result.field_name)}</h3>
          <ModeBadge mode={result.extraction_mode} />
        </div>
      </div>
      <ConfidenceBar confidence={confidence} />
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{readableContent(result.content)}</p>
      <EvidenceBlock evidence={result.evidence} />
      {result.notes && <p className="text-xs italic text-slate-500">{result.notes}</p>}
      <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-slate-400">
        <MapPin className="h-3 w-3" /><span>p.{result.page ?? "-"}</span>
        <span>{result.source || result.source_type}</span>
      </div>
    </article>
  );
}


function StatCard({ icon: Icon, label, value, sub }: { icon: typeof FileText; label: string; value: number; sub?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500"><Icon className="h-3.5 w-3.5" />{label}</div>
      <p className="mt-1 text-xl font-semibold text-slate-900">{value}</p>
      {sub && <p className="text-[10px] text-slate-400">{sub}</p>}
    </div>
  );
}

function ResultSummary({ results }: { results: ExtractionResult[] }) {
  const total = results.length;
  const successful = results.filter((r) => r.parse_status === "success").length;
  const fallbacks = results.filter(isFallback).length;
  const avgConf = results.filter((r) => r.confidence != null).reduce((s, r) => s + (r.confidence ?? 0), 0) / (results.filter((r) => r.confidence != null).length || 1);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <StatCard icon={FileText} label="总结果" value={total} />
      <StatCard icon={CheckCircle2} label="成功提取" value={successful} sub={`${Math.round((successful / (total || 1)) * 100)}%`} />
      <StatCard icon={AlertTriangle} label="Fallback" value={fallbacks} />
      <StatCard icon={Braces} label="平均置信度" value={Math.round(avgConf * 100)} sub="%" />
    </div>
  );
}

function GroupSection({ group, results, assetsById }: { group: ResultGroup; results: ExtractionResult[]; assetsById: Map<number, DocumentAsset> }) {
  const meta = group === "visual" ? { title: "图片/图表", icon: Image } : group === "table" ? { title: "表格", icon: Table2 } : { title: "正文", icon: FileText };
  const Icon = meta.icon;
  if (!results.length) return null;
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-slate-500" />
        <h2 className="text-sm font-semibold text-slate-900">{meta.title}</h2>
        <Badge variant="outline" className="text-[10px]">{results.length}</Badge>
      </div>
      <div className={group === "visual" ? "grid gap-4 sm:grid-cols-2 lg:grid-cols-3" : "grid gap-3 lg:grid-cols-2"}>
        {results.map((r) => {
          const asset = r.source_id ? assetsById.get(r.source_id) : undefined;
          if (group === "visual") return <VisualResultCard key={r.id} result={r} asset={asset} />;
          if (group === "table") return <TableResultCard key={r.id} result={r} asset={asset} />;
          return <TextResultCard key={r.id} result={r} asset={asset} />;
        })}
      </div>
    </section>
  );
}

function ResultBody({ job, assets }: { job: ExtractionJob; assets: DocumentAsset[] }) {
  const results = job.results ?? [];
  const assetsById = useMemo(() => assetMap(assets), [assets]);
  const [showRaw, setShowRaw] = useState(false);

  const grouped = useMemo(() => {
    const g: Record<ResultGroup, ExtractionResult[]> = { visual: [], table: [], text: [] };
    for (const r of results) g[groupForResult(r, assetsById)].push(r);
    return g;
  }, [results, assetsById]);

  if (!results.length) return <div className="rounded-lg bg-slate-50 p-12 text-center text-sm text-slate-400">暂无提取结果</div>;

  return (
    <div className="space-y-6">
      <ResultSummary results={results} />
      <GroupSection group="visual" results={grouped.visual} assetsById={assetsById} />
      <GroupSection group="table" results={grouped.table} assetsById={assetsById} />
      <GroupSection group="text" results={grouped.text} assetsById={assetsById} />
      <div className="pt-2">
        <Button variant="ghost" size="sm" className="text-xs text-slate-400" onClick={() => setShowRaw(!showRaw)}>
          <Braces className="mr-1 h-3.5 w-3.5" />{showRaw ? "收起" : "查看"} 原始 JSON
        </Button>
        {showRaw && <pre className="mt-2 max-h-96 overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(results, null, 2)}</pre>}
      </div>
    </div>
  );
}

export function PaperExtractionResultPage() {
  const paperId = Number(useParams().id);
  const [searchParams] = useSearchParams();
  const selectedJobId = Number(searchParams.get("job"));
  const hasSelectedJob = Number.isFinite(selectedJobId) && selectedJobId > 0;
  const queryClient = useQueryClient();

  const paperQuery = useQuery({ queryKey: ["paper", paperId], queryFn: () => getPaper(paperId), enabled: Number.isFinite(paperId), refetchInterval: (q) => shouldPollPaper(q.state.data) ? 2000 : false });
  const assetsQuery = useQuery({ queryKey: ["paper", paperId, "assets"], queryFn: () => getDocumentAssets(paperId), enabled: Number.isFinite(paperId) });
  const jobQuery = useQuery({ queryKey: ["extraction", selectedJobId], queryFn: () => getExtraction(selectedJobId), enabled: hasSelectedJob, refetchInterval: (q) => isExtractionBusy(q.state.data?.status) ? 2000 : false });
  const retryMutation = useMutation({ mutationFn: (id: number) => retryExtraction(id), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["paper", paperId] }); queryClient.invalidateQueries({ queryKey: ["extraction", selectedJobId] }); } });

  const paper = paperQuery.data;
  const job = hasSelectedJob ? jobQuery.data : paper?.latest_extraction_job;
  const loading = paperQuery.isLoading || assetsQuery.isLoading || (hasSelectedJob && jobQuery.isLoading);

  if (loading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  return (
    <main className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 px-2 text-slate-500">
            <Link to="/extractions"><ArrowLeft className="h-4 w-4" />提取任务</Link>
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            {job && <ExtractionStatusBadge status={job.status} />}
            {job && <span className="text-xs text-slate-400">#{job.id} · {formatChinaDateTime(job.updated_at)}</span>}
          </div>
          <h1 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">{paper.title}</h1>
          {job && <p className="mt-1 max-w-2xl text-sm text-slate-500">{job.query}</p>}
        </div>
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm"><Link to={`/papers/${paper.id}`}><FileText className="h-4 w-4" />论文</Link></Button>
          <Button variant="outline" size="sm" onClick={() => { paperQuery.refetch(); assetsQuery.refetch(); jobQuery.refetch(); }} disabled={paperQuery.isFetching}>
            {paperQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </Button>
        </div>
      </header>

      {!job && (
        <section className="rounded-lg border border-slate-200 bg-white p-10 text-center">
          <p className="text-sm text-slate-500">暂无提取结果</p>
          <Button asChild className="mt-4"><Link to="/extractions">创建提取任务</Link></Button>
        </section>
      )}

      {job && isExtractionBusy(job.status) && (
        <section className="rounded-lg border border-slate-200 bg-white p-10 text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-slate-400" />
          <p className="mt-3 text-sm text-slate-600">提取任务执行中...</p>
        </section>
      )}

      {job?.status === "failed" && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>{job.error_message ?? "提取失败"}</span>
            <Button size="sm" variant="outline" className="border-red-200 text-red-700" onClick={() => retryMutation.mutate(job.id)} disabled={retryMutation.isPending}>
              {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}重试
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {job?.status === "done" && <ResultBody job={job} assets={assetsQuery.data ?? []} />}
    </main>
  );
}




