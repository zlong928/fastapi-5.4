import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CalendarClock, CheckCircle2, Download, FileText, Image as ImageIcon, Loader2, RefreshCw, Table2, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { API_BASE_URL, deletePaper, getDocumentAssets, getDocumentClaims, getDocumentEvents, getPaper, getPaperAssetBlob, getToken, parsePaper } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { DocumentAsset, DocumentClaim, PaperDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PaperStatusBadge, shouldPollPaper } from "@/pages/paperShared";

type TabKey = "text" | "images" | "tables" | "logs";

const TAB_LABELS: Record<TabKey, string> = {
  text: "正文",
  images: "图片",
  tables: "表格",
  logs: "日志"
};

function assetImagePath(asset: DocumentAsset) {
  return asset.file_path ? `/papers/assets/${asset.id}` : "";
}

function textValue(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.map((item) => String(item)).join("；") || fallback;
  return String(value);
}

function imageKind(asset: DocumentAsset) {
  if (asset.asset_type === "page_snapshot") return "页面截图";
  const source = asset.metadata?.source;
  if (source === "extracted_image") return "PDF 图片对象";
  if (source === "rendered_figure_region") return "图像区域";
  return "论文图片";
}

function coordinatePreviewStatusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    accepted: "已标定",
    review_required: "需复核",
    skipped: "已跳过",
    failed: "失败",
  };
  return labels[status || ""] ?? status ?? "";
}

function coordinatePreviewTone(status?: string | null) {
  if (status === "accepted") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "review_required") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function downloadCoordinatePreview(asset: DocumentAsset) {
  const token = getToken();
  fetch(`${API_BASE_URL}/papers/assets/${asset.id}/coordinate-preview.csv`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
    .then((response) => {
      if (!response.ok) throw new Error("CSV 下载失败");
      return response.blob();
    })
    .then((blob) => {
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      const safeLabel = (asset.label || `asset-${asset.id}`).replace(/[^\w.-]+/g, "_");
      link.href = url;
      link.download = `${safeLabel}_coordinate_preview.csv`;
      document.body.appendChild(link);
      link.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(link);
    })
    .catch((error) => {
      alert(error.message || "CSV 下载失败");
    });
}

function Stat({ icon: Icon, label, value }: { icon: typeof FileText; label: string; value: string | number }) {
  return (
    <div className="min-w-0 rounded-md bg-slate-50 p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{value}</p>
    </div>
  );
}

function ClaimStrip({ claims }: { claims: DocumentClaim[] }) {
  if (!claims.length) return null;
  return (
    <section className="rounded-md border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-950">关键结论</h2>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {claims.slice(0, 4).map((claim) => (
          <article key={claim.id} className="rounded-md bg-slate-50 p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <Badge variant="outline" className="border-transparent bg-white text-slate-700">{claim.claim_type}</Badge>
              <span>page {claim.page_number ?? "-"}</span>
              <span>{claim.confidence}</span>
            </div>
            <p className="mt-2 line-clamp-2 text-sm font-medium leading-6 text-slate-900">{claim.claim_text}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function AssetImage({ asset, onOpen }: { asset: DocumentAsset; onOpen: (src: string) => void }) {
  const imagePath = assetImagePath(asset);
  const [src, setSrc] = useState("");

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    if (!imagePath) {
      setSrc("");
      return () => {};
    }
    getPaperAssetBlob(imagePath)
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
  }, [imagePath]);

  if (!imagePath) return <div className="flex aspect-[4/3] items-center justify-center rounded-md bg-slate-50 text-sm text-slate-400">无图片文件</div>;
  if (!src) return <div className="flex aspect-[4/3] items-center justify-center rounded-md bg-slate-50 text-sm text-slate-400">图片加载中</div>;
  return (
    <button type="button" onClick={() => onOpen(src)} className="block w-full rounded-md outline-none transition hover:ring-2 hover:ring-slate-300 focus-visible:ring-2 focus-visible:ring-slate-900">
      <img src={src} alt={asset.label || imageKind(asset)} className="aspect-[4/3] w-full rounded-md bg-slate-50 object-contain" />
    </button>
  );
}

function ImageAssetCard({ asset, onOpen }: { asset: DocumentAsset; onOpen: (src: string) => void }) {
  const uncertainties = Array.isArray(asset.metadata?.uncertainties) ? asset.metadata.uncertainties.map(String).filter(Boolean) : [];
  const analysisStatus = asset.metadata?.agent_analysis_status as string | undefined;
  const analysisError = asset.metadata?.agent_analysis_error as string | undefined;
  const coordinatePreview = asset.metadata?.coordinate_preview as { status?: string; row_count?: number; data_quality?: string } | undefined;
  return (
    <article id={`asset-${asset.id}`} className="rounded-md border border-slate-200 bg-white p-3">
      <AssetImage asset={asset} onOpen={onOpen} />
      <div className="mt-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-950">{asset.label || imageKind(asset)}</h3>
          <p className="mt-1 text-xs text-slate-500">page {asset.page_number ?? "-"} · asset #{asset.id}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge variant="outline" className="border-transparent bg-blue-50 text-blue-700 ring-1 ring-blue-200">{imageKind(asset)}</Badge>
          {analysisStatus === "success" ? <Badge variant="outline" className="border-transparent bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">分析完成</Badge> : null}
          {analysisStatus === "failed" ? <Badge variant="outline" className="border-transparent bg-red-50 text-red-700 ring-1 ring-red-200">分析失败</Badge> : null}
          {analysisStatus === "fallback" ? <Badge variant="outline" className="border-transparent bg-amber-50 text-amber-700 ring-1 ring-amber-200">降级模式</Badge> : null}
        </div>
      </div>
      {asset.caption ? <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600">{asset.caption}</p> : null}
      {asset.summary || asset.text_content ? <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-800">{asset.summary || asset.text_content}</p> : null}
      {coordinatePreview ? (
        <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2">
          <div className="flex items-center justify-between gap-2">
            <Badge variant="outline" className={cn("border text-[10px]", coordinatePreviewTone(coordinatePreview.status))}>
              {coordinatePreviewStatusLabel(coordinatePreview.status)}
            </Badge>
            <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-[11px]" onClick={() => downloadCoordinatePreview(asset)}>
              <Download className="h-3.5 w-3.5" />
              CSV
            </Button>
          </div>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">
            {coordinatePreview.row_count ?? 0} 点 · {coordinatePreview.data_quality || "未标注质量"}
          </p>
        </div>
      ) : null}
      {analysisError ? (
        <p className="mt-3 rounded-md bg-red-50 p-2 text-xs leading-5 text-red-800">{analysisError}</p>
      ) : null}
      {uncertainties.length ? (
        <p className="mt-3 rounded-md bg-amber-50 p-2 text-xs leading-5 text-amber-800">{uncertainties[0]}</p>
      ) : null}
    </article>
  );
}

function TableAssetCard({ asset }: { asset: DocumentAsset }) {
  const keyFindings = Array.isArray(asset.metadata?.key_findings) ? asset.metadata.key_findings.map(String).filter(Boolean) : [];
  return (
    <article id={`asset-${asset.id}`} className="rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-950">{asset.label || `Table ${asset.asset_index ?? asset.id}`}</h3>
          <p className="mt-1 text-xs text-slate-500">page {asset.page_number ?? "-"} · asset #{asset.id}</p>
        </div>
        <Badge variant="outline" className="border-transparent bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">table</Badge>
      </div>
      {asset.caption ? <p className="mt-3 text-sm leading-6 text-slate-600">{asset.caption}</p> : null}
      {asset.summary ? <p className="mt-2 text-sm leading-6 text-slate-800">{asset.summary}</p> : null}
      {keyFindings.length ? (
        <div className="mt-3 rounded-md bg-emerald-50 p-3 text-sm leading-6 text-emerald-900">
          {keyFindings.slice(0, 3).map((item, index) => <p key={index}>{item}</p>)}
        </div>
      ) : null}
      {asset.markdown ? <pre className="mt-3 max-h-64 overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-50">{asset.markdown}</pre> : null}
    </article>
  );
}

export function PaperDetailPage() {
  const paperId = Number(useParams().id);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>("text");
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  const paperQuery = useQuery({
    queryKey: ["paper", paperId],
    queryFn: () => getPaper(paperId),
    enabled: Number.isFinite(paperId),
    refetchInterval: (queryState) => shouldPollPaper(queryState.state.data) ? 2000 : false
  });
  const claimsQuery = useQuery({ queryKey: ["paper", paperId, "claims"], queryFn: () => getDocumentClaims(paperId), enabled: Number.isFinite(paperId) });
  const assetsQuery = useQuery({ queryKey: ["paper", paperId, "assets"], queryFn: () => getDocumentAssets(paperId), enabled: Number.isFinite(paperId) });
  const eventsQuery = useQuery({ queryKey: ["paper", paperId, "events"], queryFn: () => getDocumentEvents(paperId, 1, 50), enabled: Number.isFinite(paperId) });

  const paper = paperQuery.data;
  const claims = claimsQuery.data ?? [];
  const assets = assetsQuery.data ?? [];
  const events = eventsQuery.data?.items ?? [];
  const tables = useMemo(() => assets.filter((asset) => asset.asset_type === "table"), [assets]);
  const images = useMemo(() => assets.filter((asset) => {
    if (asset.asset_type === "figure") return true;
    if (asset.asset_type === "page_snapshot") {
      const source = asset.metadata?.source;
      return source === "page_visual_snapshot" || source === "rendered_figure_region";
    }
    return false;
  }), [assets]);

  const refreshMutation = useMutation({
    mutationFn: () => parsePaper(paperId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper", paperId] });
      queryClient.invalidateQueries({ queryKey: ["paper", paperId, "assets"] });
      queryClient.invalidateQueries({ queryKey: ["paper", paperId, "claims"] });
      queryClient.invalidateQueries({ queryKey: ["paper", paperId, "events"] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => deletePaper(paperId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["papers"] });
      navigate("/papers");
    }
  });

  if (paperQuery.isLoading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  const busy = refreshMutation.isPending || paper.status === "processing" || paper.status === "parsing";
  const hasFigures = images.length > 0;
  const needsReparse = paper.status === "failed" || (!hasFigures && !tables.length && paper.status === "done");

  return (
    <main className="mx-auto max-w-7xl space-y-5">
      <header className="space-y-4">
        <Button asChild variant="ghost" size="sm" className="rounded-md px-2 text-slate-500">
          <Link to="/papers"><ArrowLeft className="h-4 w-4" />论文列表</Link>
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-4xl">
            <div className="flex flex-wrap items-center gap-2">
              <PaperStatusBadge status={paper.status} />
              <span className="text-xs text-slate-400">更新：{formatChinaDateTime(paper.updated_at)}</span>
            </div>
            <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight text-slate-950">{paper.title}</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            {needsReparse ? (
              <Button variant="outline" className="rounded-md border-slate-200 shadow-none" onClick={() => refreshMutation.mutate()} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                重新解析
              </Button>
            ) : null}
            <Button asChild className="rounded-md">
              <Link to={`/papers/${paper.id}/extraction`}>提取任务</Link>
            </Button>
            <Button
              variant="outline"
              className="rounded-md border-red-200 text-red-600 shadow-none hover:bg-red-50 hover:text-red-700"
              onClick={() => { if (window.confirm("确定删除此论文？")) deleteMutation.mutate(); }}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              删除
            </Button>
          </div>
        </div>
        {paper.parse_error ? (
          <Alert variant="destructive"><AlertTriangle className="h-4 w-4" /><AlertDescription>{paper.parse_error}</AlertDescription></Alert>
        ) : null}
        {busy ? (
          <Alert><Loader2 className="h-4 w-4 animate-spin" /><AlertDescription>正在解析中，图片和表格将在解析完成后自动显示...</AlertDescription></Alert>
        ) : null}
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={FileText} label="正文字符" value={paper.text_content?.length ?? 0} />
        <Stat icon={ImageIcon} label="图片" value={images.length} />
        <Stat icon={Table2} label="表格" value={tables.length} />
        <Stat icon={CheckCircle2} label="关键结论" value={claims.length} />
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-950">基本信息</h2>
          <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
            <Info label="文件" value={paper.file_path} />
            <Info label="状态" value={paper.status} />
            <Info label="创建时间" value={formatChinaDateTime(paper.created_at)} />
            <Info label="更新时间" value={formatChinaDateTime(paper.updated_at)} />
          </dl>
        </div>
        <ClaimStrip claims={claims} />
      </section>

      <nav className="flex gap-1 overflow-x-auto border-b border-slate-200">
        {(["text", "images", "tables", "logs"] as TabKey[]).map((key) => {
          const count = key === "images" ? images.length : key === "tables" ? tables.length : key === "logs" ? events.length : 0;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
              className={cn("border-b-2 border-transparent px-3 py-3 text-sm text-slate-500 outline-none transition hover:text-slate-950 focus-visible:bg-slate-50", activeTab === key && "border-slate-950 text-slate-950")}
            >
              {TAB_LABELS[key]}{count > 0 ? ` (${count})` : ""}
            </button>
          );
        })}
      </nav>

      {activeTab === "text" ? (
        <Panel title="正文预览">
          <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-4 font-mono text-sm leading-7 text-slate-700">{paper.text_content || "暂无正文"}</pre>
        </Panel>
      ) : null}
      {activeTab === "images" ? (
        <Panel title="图片列表">
          {images.length ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{images.map((asset) => <ImageAssetCard key={asset.id} asset={asset} onOpen={setPreviewImage} />)}</div>
          ) : (
            <Empty text={busy ? "解析中，图片将在完成后显示..." : "该论文未提取到图片"} />
          )}
        </Panel>
      ) : null}
      {activeTab === "tables" ? (
        <Panel title="表格列表">
          {tables.length ? (
            <div className="grid gap-3 lg:grid-cols-2">{tables.map((asset) => <TableAssetCard key={asset.id} asset={asset} />)}</div>
          ) : (
            <Empty text={busy ? "解析中，表格将在完成后显示..." : "该论文未提取到表格"} />
          )}
        </Panel>
      ) : null}
      {activeTab === "logs" ? (
        <Panel title="操作日志">
          {events.length ? <div className="divide-y divide-slate-100 rounded-md border border-slate-200">{events.map((event) => <article key={event.id} className="p-4"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-slate-950">{event.event_type}</p><span className="inline-flex items-center gap-1 text-xs text-slate-400"><CalendarClock className="h-3.5 w-3.5" />{formatChinaDateTime(event.created_at)}</span></div><p className="mt-1 text-sm leading-6 text-slate-600">{event.message}</p></article>)}</div> : <Empty text="暂无操作日志" />}
        </Panel>
      ) : null}

      {previewImage ? <ImageModal src={previewImage} paper={paper} onClose={() => setPreviewImage(null)} /> : null}
    </main>
  );
}

function Info({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 truncate text-slate-800">{textValue(value)}</dd>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold text-slate-950">{title}</h2>
      {children}
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-md bg-slate-50 p-8 text-center text-sm text-slate-400">{text}</div>;
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
