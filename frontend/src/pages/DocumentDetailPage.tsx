import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  Copy,
  Download,
  ExternalLink,
  FileText,
  ImageIcon,
  Loader2,
  Maximize2,
  Network,
  RefreshCw,
  Trash2,
  X
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { EpubReader } from "@/components/EpubReader";
import { TagPill, TagSelector } from "@/components/TagSelector";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  deleteDocument,
  getDocument,
  getDocumentChunks,
  getDocumentEvents,
  getDocumentFileBlob,
  getDocumentFileText,
  getDocumentKg,
  reEmbedDocument,
  retryDocumentParse
} from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { DocumentChunk, DocumentRead, DocumentStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type DetailTab = "preview" | "text" | "chunks" | "events" | "graph";

function statusText(status: DocumentStatus) {
  if (status === "pending") return "等待";
  if (status === "processing") return "解析中";
  if (status === "done" || status === "completed") return "完成";
  if (status === "failed") return "失败";
  if (status === "deleted") return "已删除";
  return status;
}

function statusClass(status: DocumentStatus) {
  if (status === "pending" || status === "processing") return "bg-amber-50 text-amber-700";
  if (status === "done" || status === "completed") return "bg-emerald-50 text-emerald-700";
  if (status === "failed") return "bg-red-50 text-red-700";
  return "bg-slate-50 text-slate-500";
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, index)).toFixed(1)} ${sizes[index]}`;
}

function previewText(document?: DocumentRead) {
  return document?.cleaned_text || document?.parsed_text || "";
}

function isTextLike(document?: DocumentRead) {
  return document?.source_type === "txt" || document?.source_type === "markdown";
}

function isEpub(document?: DocumentRead) {
  return document?.source_type === "epub" || document?.mime_type === "application/epub+zip";
}

function isDone(status?: DocumentStatus) {
  return status === "done" || status === "completed";
}

function isBookmark(document?: DocumentRead) {
  return document?.source_type === "bookmark";
}

export function DocumentDetailPage() {
  const { id } = useParams();
  const documentId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState<DetailTab>("preview");
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [fileText, setFileText] = useState<string | undefined>();
  const [fullscreenOpen, setFullscreenOpen] = useState(searchParams.get("fullscreen") === "1");
  const [copied, setCopied] = useState(false);

  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId),
    enabled: Number.isFinite(documentId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 2500 : false;
    }
  });
  const document = documentQuery.data;

  const chunksQuery = useQuery({
    queryKey: ["document", documentId, "chunks"],
    queryFn: () => getDocumentChunks(documentId),
    enabled: Boolean(document && isDone(document.status))
  });

  const eventsQuery = useQuery({
    queryKey: ["document", documentId, "events"],
    queryFn: () => getDocumentEvents(documentId, 1, 20),
    enabled: Boolean(document)
  });

  const kgQuery = useQuery({
    queryKey: ["document", documentId, "kg"],
    queryFn: () => getDocumentKg(documentId),
    enabled: Boolean(document && tab === "graph")
  });

  const retryMutation = useMutation({
    mutationFn: retryDocumentParse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  const embedMutation = useMutation({
    mutationFn: reEmbedDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document", documentId, "chunks"] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => navigate("/knowledge")
  });

  useEffect(() => {
    if (!document) return;
    if (isBookmark(document)) {
      setFileUrl(null);
      setFileText(undefined);
      return;
    }
    const currentDocument = document;
    let cancelled = false;
    let objectUrl: string | null = null;

    async function loadFile() {
      try {
        const blob = await getDocumentFileBlob(currentDocument.id);
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setFileUrl(objectUrl);
        if (isTextLike(currentDocument)) {
          const text = await getDocumentFileText(currentDocument.id);
          if (!cancelled) setFileText(text);
        }
      } catch {
        if (!cancelled) setFileUrl(null);
      }
    }

    loadFile();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document?.id, document?.source_type]);

  useEffect(() => {
    if (!fullscreenOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreenOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreenOpen]);

  const text = previewText(document);
  const chunks = chunksQuery.data ?? [];
  const events = eventsQuery.data?.items ?? document?.events ?? [];
  const errorText = document?.processing_error || document?.fail_reason || document?.error_message;

  const tabs = useMemo(() => [
    { key: "preview" as const, label: "预览" },
    { key: "text" as const, label: "文本" },
    { key: "chunks" as const, label: `片段${chunks.length ? ` ${chunks.length}` : ""}` },
    { key: "events" as const, label: "事件" },
    { key: "graph" as const, label: "图谱" }
  ], [chunks.length]);

  async function copyText() {
    if (!text) return;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  function openFile() {
    if (isBookmark(document) && document?.source_url) {
      window.open(document.source_url, "_blank", "noopener,noreferrer");
      return;
    }
    if (fileUrl) window.open(fileUrl, "_blank", "noopener,noreferrer");
  }

  function downloadFile() {
    if (!fileUrl || !document) return;
    const anchor = window.document.createElement("a");
    anchor.href = fileUrl;
    anchor.download = document.original_filename;
    anchor.click();
  }

  if (documentQuery.isLoading) {
    return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">加载中</div>;
  }

  if (documentQuery.isError || !document) {
    return (
      <div className="mx-auto max-w-3xl rounded-3xl border border-red-100 bg-red-50 p-4 text-sm text-red-600">
        {documentQuery.error instanceof Error ? documentQuery.error.message : "加载失败"}
      </div>
    );
  }

  return (
    <div className="mx-auto grid min-h-[calc(100vh-6rem)] max-w-7xl gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <main className="min-w-0 rounded-3xl border border-slate-100 bg-white p-4">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Button type="button" variant="ghost" size="sm" className="mb-2 h-8 rounded-xl px-2 text-slate-500" onClick={() => navigate("/knowledge")}>
              <ChevronLeft className="h-4 w-4" />
              知识库
            </Button>
            <h1 className="truncate text-2xl font-semibold tracking-tight text-slate-950">{document.title}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <span>{document.source_type.toUpperCase()}</span>
              <span>{formatBytes(document.file_size)}</span>
              <span>{formatChinaDateTime(document.uploaded_at)}</span>
              {document.chunk_count ? <span>{document.chunk_count} chunks</span> : null}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={() => retryMutation.mutate(document.id)} disabled={retryMutation.isPending}>
              {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              重试
            </Button>
            {!isBookmark(document) ? (
              <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={downloadFile} disabled={!fileUrl}>
                <Download className="h-4 w-4" />
              </Button>
            ) : null}
            <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 text-red-500 shadow-none" onClick={() => confirm("删除文档？") && deleteMutation.mutate(document.id)} disabled={deleteMutation.isPending}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {errorText ? (
          <Alert variant="destructive" className="mb-4 rounded-2xl border-red-100">
            <AlertDescription>{errorText}</AlertDescription>
          </Alert>
        ) : null}

        <div className="mb-4 flex flex-wrap gap-1 rounded-2xl bg-slate-50 p-1">
          {tabs.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              className={cn("rounded-xl px-3 py-2 text-sm text-slate-500 transition hover:text-slate-950", tab === item.key && "bg-white text-slate-950 ring-1 ring-slate-100")}
            >
              {item.label}
            </button>
          ))}
        </div>

        {tab === "preview" ? (
          <PreviewPane document={document} fileUrl={fileUrl} fileText={fileText} onFullscreen={() => setFullscreenOpen(true)} />
        ) : null}

        {tab === "text" ? (
          <TextPane text={text} copied={copied} onCopy={copyText} />
        ) : null}

        {tab === "chunks" ? (
          <ChunksPane chunks={chunks} isLoading={chunksQuery.isLoading} status={document.status} />
        ) : null}

        {tab === "events" ? (
          <EventsPane events={events} />
        ) : null}

        {tab === "graph" ? (
          <GraphPane entities={kgQuery.data?.entities ?? []} relations={kgQuery.data?.relations ?? []} isLoading={kgQuery.isLoading} />
        ) : null}
      </main>

      <aside className="space-y-3">
        <div className="rounded-3xl border border-slate-100 bg-white p-4">
          <div className="flex items-center justify-between gap-3">
            <span className={cn("inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs", statusClass(document.status))}>
              {isDone(document.status) ? <CheckCircle2 className="h-3.5 w-3.5" /> : document.status === "failed" ? <AlertCircle className="h-3.5 w-3.5" /> : <RefreshCw className="h-3.5 w-3.5" />}
              {statusText(document.status)}
            </span>
            <Button type="button" variant="ghost" size="sm" className="h-8 rounded-xl px-2" onClick={openFile} disabled={isBookmark(document) ? !document.source_url : !fileUrl}>
              <ExternalLink className="h-4 w-4" />
            </Button>
          </div>

          <div className="mt-4 space-y-2 text-sm text-slate-500">
            <InfoRow label="文件" value={document.original_filename} />
            {isBookmark(document) ? <InfoRow label="站点" value={document.site_name || "-"} /> : null}
            {isBookmark(document) ? <InfoRow label="来源" value={document.source_url || "-"} /> : null}
            <InfoRow label="模式" value={document.processing_mode} />
            <InfoRow label="集合" value={document.collection_name || "-"} />
            <InfoRow label="解析" value={document.parsed_at ? formatChinaDateTime(document.parsed_at) : "-"} />
          </div>
        </div>

        <div className="rounded-3xl border border-slate-100 bg-white p-4">
          <p className="mb-3 text-sm font-medium text-slate-700">标签</p>
          <div className="mb-3 flex flex-wrap gap-2">
            {document.tags.length ? document.tags.map((tag) => <TagPill key={tag.id} tag={tag} />) : <span className="text-sm text-slate-400">无</span>}
          </div>
          <TagSelector documentIds={[document.id]} compact />
        </div>

        <div className="rounded-3xl border border-slate-100 bg-white p-4">
          <p className="mb-3 text-sm font-medium text-slate-700">操作</p>
          <div className="space-y-2">
            <Button type="button" variant="outline" className="w-full justify-start rounded-xl border-slate-100 shadow-none" onClick={() => embedMutation.mutate(document.id)} disabled={embedMutation.isPending || !chunks.length}>
              {embedMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
              重建 Embedding
            </Button>
            <Button asChild variant="outline" className="w-full justify-start rounded-xl border-slate-100 shadow-none">
              <Link to={`/notes?documentId=${document.id}`}>关联笔记</Link>
            </Button>
          </div>
        </div>
      </aside>

      {fullscreenOpen && fileUrl ? (
        <FullscreenPreview document={document} fileUrl={fileUrl} fileText={fileText ?? text} onClose={() => setFullscreenOpen(false)} />
      ) : null}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <span className="w-10 shrink-0 text-slate-400">{label}</span>
      <span className="min-w-0 flex-1 truncate text-slate-700">{value}</span>
    </div>
  );
}

function PreviewPane({ document, fileUrl, fileText, onFullscreen }: { document: DocumentRead; fileUrl: string | null; fileText?: string; onFullscreen: () => void }) {
  if (isBookmark(document)) {
    const text = previewText(document);
    return (
      <div className="space-y-3">
        <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">
          <p className="text-sm font-medium text-slate-700">{document.site_name || "链接"}</p>
          {document.source_url ? (
            <a href={document.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700">
              <ExternalLink className="h-4 w-4" />
              打开原链接
            </a>
          ) : null}
        </div>
        {text ? <pre className="max-h-[68vh] overflow-y-auto whitespace-pre-wrap rounded-2xl bg-slate-50 p-5 text-sm leading-7 text-slate-700">{text}</pre> : <EmptyPane text="无文本" />}
      </div>
    );
  }

  if (!fileUrl) return <EmptyPane text="无预览" />;

  if (document.source_type === "pdf") {
    return (
      <div className="overflow-hidden rounded-2xl border border-slate-100 bg-slate-50">
        <div className="flex justify-end p-2"><Button size="sm" variant="ghost" className="rounded-xl" onClick={onFullscreen}><Maximize2 className="h-4 w-4" /></Button></div>
        <iframe src={fileUrl} title={document.original_filename} className="h-[68vh] min-h-[560px] w-full border-0" />
      </div>
    );
  }

  if (document.source_type === "image") {
    return (
      <div className="flex min-h-[560px] items-center justify-center rounded-2xl bg-slate-50 p-4">
        <img src={fileUrl} alt={document.original_filename} className="max-h-[68vh] max-w-full object-contain" />
      </div>
    );
  }

  if (isEpub(document)) return <EpubReader title={document.title} fileUrl={fileUrl} progressKey={`document-epub-progress-${document.id}`} />;

  if (document.source_type === "markdown" && fileText !== undefined) {
    return <div className="prose max-w-none rounded-2xl bg-slate-50 p-5"><ReactMarkdown remarkPlugins={[remarkGfm]}>{fileText}</ReactMarkdown></div>;
  }

  if (fileText !== undefined) return <pre className="min-h-[560px] whitespace-pre-wrap rounded-2xl bg-slate-50 p-5 text-sm leading-7 text-slate-700">{fileText}</pre>;

  return <EmptyPane text="无预览" />;
}

function TextPane({ text, copied, onCopy }: { text: string; copied: boolean; onCopy: () => void }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm text-slate-400">
        <span>{text.length.toLocaleString()} chars</span>
        <Button size="sm" variant="outline" className="rounded-xl border-slate-100 shadow-none" onClick={onCopy} disabled={!text}>
          <Copy className="h-4 w-4" />
          {copied ? "已复制" : "复制"}
        </Button>
      </div>
      {text ? <pre className="max-h-[68vh] overflow-y-auto whitespace-pre-wrap rounded-2xl bg-slate-50 p-5 text-sm leading-7 text-slate-700">{text}</pre> : <EmptyPane text="无文本" />}
    </div>
  );
}

function ChunksPane({ chunks, isLoading, status }: { chunks: DocumentChunk[]; isLoading: boolean; status: DocumentStatus }) {
  if (status === "pending" || status === "processing") return <EmptyPane text="解析中" />;
  if (status === "failed") return <EmptyPane text="无片段" />;
  if (isLoading) return <EmptyPane text="加载中" />;
  if (!chunks.length) return <EmptyPane text="无片段" />;

  return (
    <div className="space-y-2">
      {chunks.map((chunk) => (
        <div key={chunk.id} className="rounded-2xl border border-slate-100 bg-white p-4 hover:bg-slate-50">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span>#{chunk.chunk_index}</span>
            <span>{chunk.chunk_type}</span>
            {chunk.page_start ? <span>p.{chunk.page_start}</span> : null}
            {chunk.embedding_model ? <span>{chunk.embedding_model}</span> : null}
          </div>
          <p className="line-clamp-5 text-sm leading-6 text-slate-700">{chunk.cleaned_text || chunk.text}</p>
        </div>
      ))}
    </div>
  );
}

function EventsPane({ events }: { events: DocumentRead["events"] }) {
  if (!events.length) return <EmptyPane text="无事件" />;
  return (
    <div className="space-y-2">
      {events.map((event) => (
        <div key={event.id} className="rounded-2xl border border-slate-100 bg-white px-4 py-3 hover:bg-slate-50">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="font-medium text-slate-800">{event.event_type}</span>
            <span className="text-xs text-slate-400">{formatChinaDateTime(event.created_at)}</span>
          </div>
          <p className="mt-1 text-sm text-slate-500">{event.message}</p>
        </div>
      ))}
    </div>
  );
}

function GraphPane({ entities, relations, isLoading }: { entities: { id: number; name: string; entity_type: string }[]; relations: { id: number; subject_text: string; predicate: string; object_text: string }[]; isLoading: boolean }) {
  if (isLoading) return <EmptyPane text="加载中" />;
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="rounded-2xl border border-slate-100 p-4">
        <p className="mb-3 text-sm font-medium text-slate-700">实体</p>
        <div className="flex flex-wrap gap-2">
          {entities.length ? entities.slice(0, 80).map((entity) => <span key={entity.id} className="rounded-full bg-slate-50 px-2.5 py-1 text-xs text-slate-600">{entity.name}</span>) : <span className="text-sm text-slate-400">无</span>}
        </div>
      </div>
      <div className="rounded-2xl border border-slate-100 p-4">
        <p className="mb-3 text-sm font-medium text-slate-700">关系</p>
        <div className="space-y-2">
          {relations.length ? relations.slice(0, 40).map((relation) => <p key={relation.id} className="text-sm text-slate-600">{relation.subject_text} · {relation.predicate} · {relation.object_text}</p>) : <span className="text-sm text-slate-400">无</span>}
        </div>
      </div>
    </div>
  );
}

function EmptyPane({ text }: { text: string }) {
  return <div className="flex min-h-[360px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-slate-50 text-sm text-slate-400">{text}</div>;
}

function FullscreenPreview({ document, fileUrl, fileText, onClose }: { document: DocumentRead; fileUrl: string; fileText: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950 text-white">
      <div className="flex h-12 items-center justify-between gap-3 border-b border-white/10 px-4">
        <p className="truncate text-sm font-medium">{document.original_filename}</p>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" size="sm" className="text-white hover:bg-white/10 hover:text-white" onClick={() => window.open(fileUrl, "_blank", "noopener,noreferrer")}>
            <ExternalLink className="h-4 w-4" />
          </Button>
          <Button type="button" variant="ghost" size="sm" className="text-white hover:bg-white/10 hover:text-white" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
      {document.source_type === "pdf" ? (
        <iframe src={fileUrl} title={document.original_filename} className="min-h-0 flex-1 border-0 bg-white" />
      ) : document.source_type === "image" ? (
        <div className="min-h-0 flex-1 overflow-auto p-6"><img src={fileUrl} alt={document.original_filename} className="mx-auto max-h-full max-w-full object-contain" /></div>
      ) : isEpub(document) ? (
        <div className="min-h-0 flex-1 bg-white text-slate-950"><EpubReader title={document.title} fileUrl={fileUrl} progressKey={`document-epub-progress-${document.id}`} heightClassName="h-[calc(100vh-3rem)] min-h-0" /></div>
      ) : document.source_type === "markdown" ? (
        <div className="prose prose-invert min-h-0 flex-1 max-w-none overflow-y-auto p-6"><ReactMarkdown remarkPlugins={[remarkGfm]}>{fileText}</ReactMarkdown></div>
      ) : (
        <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap p-6 text-sm leading-7">{fileText}</pre>
      )}
    </div>
  );
}
