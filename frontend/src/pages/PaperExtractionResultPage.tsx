import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Braces, FileText, Image, Loader2, MapPin, RefreshCw, RotateCw, Table2 } from "lucide-react";
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

function flattenContentValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(flattenContentValue).filter(Boolean).join("\n");
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, entry]) => {
        const flattened = flattenContentValue(entry);
        return flattened ? `${key}: ${flattened}` : "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return String(value);
}

function readableContent(content: string) {
  const trimmed = content.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return content;
  try {
    return flattenContentValue(JSON.parse(trimmed)) || content;
  } catch {
    return content;
  }
}

function rawJson(result: ExtractionResult) {
  return JSON.stringify(
    {
      id: result.id,
      job_id: result.job_id,
      source_type: result.source_type,
      source_id: result.source_id,
      field_name: result.field_name,
      content: result.content,
      evidence: result.evidence,
      confidence: result.confidence,
      evidence_type: result.evidence_type,
      image_url: result.image_url,
      thumbnail_url: result.thumbnail_url,
      page: result.page,
      bbox: result.bbox,
      caption: result.caption,
      source: result.source,
      created_at: result.created_at
    },
    null,
    2
  );
}

function assetMap(assets: DocumentAsset[]) {
  return new Map(assets.map((asset) => [asset.id, asset]));
}

function metadataString(asset: DocumentAsset | undefined, key: string) {
  const value = asset?.metadata?.[key];
  return typeof value === "string" && value.trim() ? value : "";
}

function metadataNumberArray(asset: DocumentAsset | undefined, key: string) {
  const value = asset?.metadata?.[key];
  return Array.isArray(value) ? value.map(Number).filter((item) => Number.isFinite(item)) : null;
}

function normalizeEvidenceType(value: unknown): EvidenceType {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (["text", "table", "figure", "chart", "equation", "page_region", "unknown"].includes(normalized)) return normalized as EvidenceType;
  if (["image", "visual", "picture"].includes(normalized)) return "figure";
  if (["text_region", "ocr_text"].includes(normalized)) return "text";
  return "unknown";
}

function evidenceTypeForResult(result: ExtractionResult, assetsById: Map<number, DocumentAsset>): EvidenceType {
  const explicitType = normalizeEvidenceType(result.evidence_type);
  if (explicitType !== "unknown") return explicitType;
  if (result.source_type === "text" || !result.source_id) return "text";
  const asset = assetsById.get(result.source_id);
  const metadataType = normalizeEvidenceType(asset?.metadata?.evidence_type ?? asset?.metadata?.evidenceType);
  if (metadataType !== "unknown") return metadataType;
  const source = metadataString(asset, "source");
  const visualRole = metadataString(asset, "visual_role");
  if (asset?.asset_type === "table" || result.source_type === "table") return "table";
  if (asset?.asset_type === "page_snapshot" || source === "page_visual_snapshot" || source === "fallback_snapshot") return "page_region";
  if (source === "rendered_figure_region" && visualRole !== "figure_candidate") return "page_region";
  if (asset?.asset_type === "figure" || result.source_type === "figure") return "figure";
  return "unknown";
}

function groupForResult(result: ExtractionResult, assetsById: Map<number, DocumentAsset>): ResultGroup {
  const evidenceType = evidenceTypeForResult(result, assetsById);
  if (evidenceType === "figure" || evidenceType === "chart") return "visual";
  if (evidenceType === "table") return "table";
  return "text";
}

function groupMeta(group: ResultGroup) {
  if (group === "visual") return { title: "图片/图表证据", icon: Image };
  if (group === "table") return { title: "表格结果", icon: Table2 };
  return { title: "文本证据", icon: FileText };
}

function previewPath(result: ExtractionResult, asset?: DocumentAsset) {
  const metadataThumbnail = metadataString(asset, "thumbnailUrl");
  const metadataImage = metadataString(asset, "imageUrl");
  if (result.thumbnail_url) return result.thumbnail_url;
  if (result.image_url) return result.image_url;
  if (metadataThumbnail) return metadataThumbnail;
  if (metadataImage) return metadataImage;
  if (asset?.file_path && String(asset.mime_type || "").startsWith("image/")) return `/papers/assets/${asset.id}`;
  return "";
}

function EvidenceLocation({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  const page = result.page ?? asset?.page_number;
  const bbox = result.bbox ?? metadataNumberArray(asset, "bbox");
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
      <MapPin className="h-3.5 w-3.5" />
      <span>page {page ?? "-"}</span>
      {bbox ? <span>bbox {bbox.map((value) => Number(value).toFixed(0)).join(", ")}</span> : null}
      <span>{result.source || metadataString(asset, "source") || result.source_type}</span>
    </div>
  );
}

function EvidencePreview({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  const path = previewPath(result, asset);
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSrc("");
    setFailed(false);
    if (!path) return () => {};
    getPaperAssetBlob(path)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (!path || failed) {
    return (
      <div className="flex aspect-[4/3] flex-col items-center justify-center rounded-md bg-slate-50 p-4 text-center text-sm text-slate-400">
        <Image className="mb-2 h-5 w-5" />
        无法预览
      </div>
    );
  }
  if (!src) return <div className="flex aspect-[4/3] items-center justify-center rounded-md bg-slate-50 text-sm text-slate-400">图片加载中</div>;
  return <img src={src} alt={result.caption || asset?.caption || fieldLabel(result.field_name)} className="aspect-[4/3] w-full rounded-md bg-slate-50 object-contain" />;
}

function ConfidenceMeter({ confidence }: { confidence: number | null }) {
  if (confidence === null) return null;
  return (
    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
      <div className="h-full rounded-full bg-slate-900" style={{ width: `${confidence}%` }} />
    </div>
  );
}

function ResultHeader({ result, asset, evidenceType }: { result: ExtractionResult; asset?: DocumentAsset; evidenceType: EvidenceType }) {
  const confidence = confidencePercent(result.confidence);
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-950">{fieldLabel(result.field_name)}</h3>
          {asset ? <Badge variant="outline" className="border-transparent bg-slate-100 text-slate-700">{evidenceType} #{asset.id}</Badge> : <Badge variant="outline">{evidenceType}</Badge>}
        </div>
        {confidence !== null ? <span className="text-xs font-medium text-slate-500">{confidence}%</span> : null}
      </div>
      <ConfidenceMeter confidence={confidence} />
    </>
  );
}

function RawDetails({ result }: { result: ExtractionResult }) {
  return (
    <details className="mt-3 rounded-md bg-slate-950 p-3 text-xs text-slate-50">
      <summary className="flex cursor-pointer items-center gap-2 text-slate-200"><Braces className="h-4 w-4" />原始 JSON</summary>
      <pre className="mt-3 overflow-auto whitespace-pre-wrap leading-5">{rawJson(result)}</pre>
    </details>
  );
}

function TextResultCard({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  return (
    <article className="rounded-md border border-slate-200 bg-white p-4">
      <ResultHeader result={result} asset={asset} evidenceType="text" />
      <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-800">{readableContent(result.content)}</p>
      {result.evidence ? (
        <div className="mt-3 rounded-md bg-slate-50 p-3">
          <p className="mb-1 text-xs font-medium text-slate-500">文本证据</p>
          <p className="line-clamp-5 text-xs leading-5 text-slate-600">{result.evidence}</p>
        </div>
      ) : null}
      <EvidenceLocation result={result} asset={asset} />
      <RawDetails result={result} />
    </article>
  );
}

function VisualResultCard({ result, asset, evidenceType }: { result: ExtractionResult; asset?: DocumentAsset; evidenceType: EvidenceType }) {
  return (
    <article className="rounded-md border border-slate-200 bg-white p-4">
      <EvidencePreview result={result} asset={asset} />
      <div className="mt-4">
        <ResultHeader result={result} asset={asset} evidenceType={evidenceType} />
      </div>
      {result.caption || asset?.caption ? <p className="mt-3 text-sm leading-6 text-slate-600">{result.caption || asset?.caption}</p> : null}
      <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-800">{readableContent(result.content)}</p>
      {result.evidence ? <p className="mt-3 rounded-md bg-slate-50 p-3 text-xs leading-5 text-slate-600">{result.evidence}</p> : null}
      <EvidenceLocation result={result} asset={asset} />
      <RawDetails result={result} />
    </article>
  );
}

function TableResultCard({ result, asset }: { result: ExtractionResult; asset?: DocumentAsset }) {
  const tablePreview = asset?.markdown || asset?.text_content || readableContent(result.content);
  return (
    <article className="rounded-md border border-slate-200 bg-white p-4">
      <ResultHeader result={result} asset={asset} evidenceType="table" />
      {asset?.caption || result.caption ? <p className="mt-3 text-sm leading-6 text-slate-600">{result.caption || asset?.caption}</p> : null}
      <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs leading-5 text-slate-700">{tablePreview}</pre>
      {result.evidence ? <p className="mt-3 rounded-md bg-emerald-50 p-3 text-xs leading-5 text-emerald-900">{result.evidence}</p> : null}
      <EvidenceLocation result={result} asset={asset} />
      <RawDetails result={result} />
    </article>
  );
}

function ResultGroupSection({ group, results, assetsById }: { group: ResultGroup; results: ExtractionResult[]; assetsById: Map<number, DocumentAsset> }) {
  const meta = groupMeta(group);
  const Icon = meta.icon;
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-slate-500" />
        <h2 className="text-sm font-semibold text-slate-950">{meta.title}</h2>
        <span className="text-xs text-slate-400">{results.length}</span>
      </div>
      {results.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {results.map((result) => {
            const asset = result.source_id ? assetsById.get(result.source_id) : undefined;
            const evidenceType = evidenceTypeForResult(result, assetsById);
            if (group === "visual") return <VisualResultCard key={result.id} result={result} asset={asset} evidenceType={evidenceType} />;
            if (group === "table") return <TableResultCard key={result.id} result={result} asset={asset} />;
            return <TextResultCard key={result.id} result={result} asset={asset} />;
          })}
        </div>
      ) : <div className="rounded-md bg-slate-50 p-8 text-center text-sm text-slate-400">暂无{group === "visual" ? "图片结果" : meta.title}</div>}
    </section>
  );
}

function ResultBody({ job, assets }: { job: ExtractionJob; assets: DocumentAsset[] }) {
  const results = job.results ?? [];
  const assetsById = useMemo(() => assetMap(assets), [assets]);
  const grouped = results.reduce<Record<ResultGroup, ExtractionResult[]>>(
    (groups, result) => {
      groups[groupForResult(result, assetsById)].push(result);
      return groups;
    },
    { visual: [], table: [], text: [] }
  );

  if (!results.length) return <div className="rounded-md bg-slate-50 p-10 text-center text-sm text-slate-400">暂无提取结果</div>;

  return (
    <div className="space-y-6">
      <section className="rounded-md bg-slate-50 p-3 text-xs text-slate-500">正文结果按文本证据展示；页面截图和纯文字区域不会进入图片/图表证据。</section>
      <ResultGroupSection group="visual" results={grouped.visual} assetsById={assetsById} />
      <ResultGroupSection group="table" results={grouped.table} assetsById={assetsById} />
      <ResultGroupSection group="text" results={grouped.text} assetsById={assetsById} />
      <section>
        <div className="mb-3 flex items-center gap-2">
          <Braces className="h-4 w-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-950">原始 JSON</h2>
        </div>
        <pre className="max-h-96 overflow-auto rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-50">{JSON.stringify(results, null, 2)}</pre>
      </section>
    </div>
  );
}

export function PaperExtractionResultPage() {
  const paperId = Number(useParams().id);
  const [searchParams] = useSearchParams();
  const selectedJobId = Number(searchParams.get("job"));
  const hasSelectedJob = Number.isFinite(selectedJobId) && selectedJobId > 0;
  const queryClient = useQueryClient();

  const paperQuery = useQuery({
    queryKey: ["paper", paperId],
    queryFn: () => getPaper(paperId),
    enabled: Number.isFinite(paperId),
    refetchInterval: (queryState) => shouldPollPaper(queryState.state.data) ? 2000 : false
  });
  const assetsQuery = useQuery({ queryKey: ["paper", paperId, "assets"], queryFn: () => getDocumentAssets(paperId), enabled: Number.isFinite(paperId) });
  const jobQuery = useQuery({
    queryKey: ["extraction", selectedJobId],
    queryFn: () => getExtraction(selectedJobId),
    enabled: hasSelectedJob,
    refetchInterval: (queryState) => isExtractionBusy(queryState.state.data?.status) ? 2000 : false
  });
  const retryMutation = useMutation({
    mutationFn: (jobId: number) => retryExtraction(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper", paperId] });
      queryClient.invalidateQueries({ queryKey: ["extraction", selectedJobId] });
    }
  });

  const paper = paperQuery.data;
  const job = hasSelectedJob ? jobQuery.data : paper?.latest_extraction_job;
  const loading = paperQuery.isLoading || assetsQuery.isLoading || (hasSelectedJob && jobQuery.isLoading);

  if (loading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  return (
    <main className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-3 rounded-md px-2 text-slate-500">
            <Link to="/extractions"><ArrowLeft className="h-4 w-4" />提取任务</Link>
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            {job ? <ExtractionStatusBadge status={job.status} /> : null}
            {job ? <span className="text-xs text-slate-400">任务 #{job.id} · {formatChinaDateTime(job.updated_at)}</span> : null}
          </div>
          <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight text-slate-950">{paper.title}</h1>
          {job ? <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{job.query}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" className="rounded-md border-slate-200 shadow-none">
            <Link to={`/papers/${paper.id}`}><FileText className="h-4 w-4" />论文详情</Link>
          </Button>
          <Button variant="outline" className="rounded-md border-slate-200 shadow-none" onClick={() => { paperQuery.refetch(); assetsQuery.refetch(); jobQuery.refetch(); }} disabled={paperQuery.isFetching || assetsQuery.isFetching || jobQuery.isFetching}>
            {paperQuery.isFetching || assetsQuery.isFetching || jobQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </Button>
        </div>
      </header>

      {!job ? (
        <section className="rounded-md border border-slate-200 bg-white p-10 text-center">
          <p className="text-sm text-slate-500">暂无提取结果</p>
          <Button asChild className="mt-4 rounded-md"><Link to="/extractions">创建提取任务</Link></Button>
        </section>
      ) : null}

      {job && isExtractionBusy(job.status) ? (
        <section className="rounded-md border border-slate-200 bg-white p-10 text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-slate-400" />
          <p className="mt-3 text-sm font-medium text-slate-700">提取任务正在执行</p>
        </section>
      ) : null}

      {job?.status === "failed" ? (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{job.error_message ?? "提取失败"}</span>
            <Button type="button" size="sm" variant="outline" className="rounded-md border-red-200 bg-white text-red-700 shadow-none hover:bg-red-50" onClick={() => retryMutation.mutate(job.id)} disabled={retryMutation.isPending}>
              {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}
              重试
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {job?.status === "done" ? <ResultBody job={job} assets={assetsQuery.data ?? []} /> : null}
    </main>
  );
}
