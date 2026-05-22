import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  Copy,
  Download,
  ExternalLink,
  FileSearch,
  Filter,
  RefreshCw,
  Trash2,
  Clock,
  Network,
  ImageIcon,
  Sparkles,
  FileText,
  MapPin,
  Maximize2,
  X,
  BrainCircuit
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { EpubReader } from "@/components/EpubReader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { TagPill, TagSelector } from "@/components/TagSelector";
import { deleteDocument, getDocument, getDocumentChunks, getDocumentFileBlob, getDocumentFileText, getDocumentKg, reEmbedDocument, retryDocumentParse } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { DocumentChunk, DocumentRead, DocumentStatus, processingModeLabel } from "@/lib/types";
import { cn } from "@/lib/utils";

type DetailTab = "preview" | "text" | "chunks" | "diagnostics" | "events";

function getStatusIcon(status: DocumentStatus) {
  switch (status) {
    case "pending":
    case "processing":
      return <Clock className="h-5 w-5 text-yellow-600" />;
    case "done":
    case "completed":
      return <CheckCircle2 className="h-5 w-5 text-emerald-600" />;
    case "failed":
      return <AlertCircle className="h-5 w-5 text-red-600" />;
    case "deleted":
      return <Trash2 className="h-5 w-5 text-slate-400" />;
    default:
      return null;
  }
}

function getStatusText(status: DocumentStatus) {
  switch (status) {
    case "pending":
      return "Pending";
    case "processing":
      return "Processing";
    case "done":
      return "Done";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "deleted":
      return "Deleted";
    default:
      return status;
  }
}

function getStatusColor(status: DocumentStatus) {
  switch (status) {
    case "pending":
    case "processing":
      return "bg-yellow-50 text-yellow-700 border-yellow-200";
    case "done":
    case "completed":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "failed":
      return "bg-red-50 text-red-700 border-red-200";
    case "deleted":
      return "bg-slate-50 text-slate-600 border-slate-200";
    default:
      return "bg-slate-50 text-slate-600 border-slate-200";
  }
}

function isDoneStatus(status?: DocumentStatus | string | null) {
  return status === "done" || status === "completed";
}

function parseChunkMetadata(chunk: DocumentChunk): Record<string, unknown> | null {
  if (!chunk.metadata_json) return null;
  try {
    return JSON.parse(chunk.metadata_json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function parseJsonObject(value?: string | null): Record<string, unknown> | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function asNumber(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asString(value: unknown, fallback = "Unknown") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function asBooleanLabel(value: unknown) {
  return typeof value === "boolean" ? String(value) : "Unknown";
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function pageRangeLabel(chunk: DocumentChunk) {
  if (!chunk.page_start) return "Page unknown";
  if (chunk.page_end && chunk.page_end !== chunk.page_start) return `Pages ${chunk.page_start}-${chunk.page_end}`;
  return `Page ${chunk.page_start}`;
}

function metadataWarnings(metadata: Record<string, unknown> | null): string[] {
  const warnings = asArray(metadata?.warnings).filter((warning): warning is string => typeof warning === "string");
  return warnings;
}

function hasBBox(metadata: Record<string, unknown> | null) {
  return Array.isArray(metadata?.bbox);
}

function qualityStatus(quality: Record<string, unknown> | null) {
  if (!quality) return { label: "Unknown", className: "bg-slate-100 text-slate-700 border-slate-200" };
  const pagesTotal = asNumber(quality.pages_total ?? quality.page_count, 0);
  const pagesOcr = asNumber(quality.pages_ocr_used, 0);
  const pagesText = asNumber(quality.pages_text_extracted, pagesTotal);
  const badTextPages = asArray(quality.bad_text_pages).length;
  const scannedPages = asArray(quality.scanned_pages).length;
  const warnings = asArray(quality.warnings).length;
  const pymupdfAvailable = quality.pymupdf_available;
  const poor =
    pymupdfAvailable === false ||
    warnings >= 8 ||
    (pagesTotal > 0 && (pagesText / pagesTotal < 0.35 || pagesOcr / pagesTotal >= 0.6));
  if (poor) return { label: "Poor", className: "bg-red-50 text-red-700 border-red-200" };
  const warning = pagesOcr > 0 || badTextPages > 0 || scannedPages > 0 || warnings > 0;
  if (warning) return { label: "Warning", className: "bg-amber-50 text-amber-700 border-amber-200" };
  return { label: "Good", className: "bg-emerald-50 text-emerald-700 border-emerald-200" };
}

function qualityStat(quality: Record<string, unknown> | null, key: string, fallback: string | number = "Unknown") {
  if (!quality || quality[key] === undefined || quality[key] === null) return String(fallback);
  const value = quality[key];
  if (Array.isArray(value)) return value.length ? value.join(", ") : "0";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function TextPreview({
  title,
  text,
  copied,
  onCopy,
  emptyMessage,
  previewLength = 2600
}: {
  title: string;
  text?: string | null;
  copied: boolean;
  onCopy: () => void;
  emptyMessage: string;
  previewLength?: number;
}) {
  const [showFull, setShowFull] = useState(false);
  const value = text || "";
  const isLong = value.length > previewLength;
  const visibleText = showFull || !isLong ? value : `${value.slice(0, previewLength)}...`;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">{value.length.toLocaleString()} characters</p>
        </div>
        <div className="flex gap-2">
          {isLong && (
            <Button size="sm" variant="outline" onClick={() => setShowFull((current) => !current)}>
              {showFull ? "Hide full text" : "Show full text"}
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={onCopy} className="gap-2" disabled={!value}>
            <Copy className="h-4 w-4" />
            {copied ? "Copied!" : "Copy"}
          </Button>
        </div>
      </div>
      {value ? (
        <div className="max-h-80 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4">
          <pre className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{visibleText}</pre>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500">
          {emptyMessage}
        </div>
      )}
    </div>
  );
}

function ParsingQualityPanel({ quality }: { quality: Record<string, unknown> | null }) {
  const status = qualityStatus(quality);
  const warnings = asArray(quality?.warnings).filter((warning): warning is string => typeof warning === "string");
  const imageBlocks = qualityStat(quality, "image_block_count_total", qualityStat(quality, "image_block_count", 0));
  const stats = [
    ["Parser Engine", asString(quality?.parser_engine)],
    ["PyMuPDF Available", asBooleanLabel(quality?.pymupdf_available)],
    ["Pages Total", qualityStat(quality, "pages_total", qualityStat(quality, "page_count", "Unknown"))],
    ["Text Extracted Pages", qualityStat(quality, "pages_text_extracted", "Unknown")],
    ["OCR Pages", qualityStat(quality, "pages_ocr_used", 0)],
    ["Scanned Pages", String(asArray(quality?.scanned_pages).length)],
    ["Bad Text Pages", String(asArray(quality?.bad_text_pages).length)],
    ["Image Blocks", imageBlocks],
    ["Table Count", qualityStat(quality, "table_count", 0)],
    ["Warnings", String(warnings.length)]
  ];
  const pageProfiles = asArray(quality?.page_profiles).filter(
    (profile): profile is Record<string, unknown> => Boolean(profile && typeof profile === "object" && !Array.isArray(profile))
  );

  return (
    <Card>
      <CardHeader className="border-b border-slate-200 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FileSearch className="h-5 w-5 text-blue-600" />
            <h2 className="font-semibold">Parsing Quality</h2>
          </div>
          <span className={cn("rounded-full border px-3 py-1 text-sm font-medium", status.className)}>
            {status.label}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-5 p-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {stats.map(([label, value]) => (
            <div key={label} className="rounded-md border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
              <p className="mt-1 break-words text-base font-medium text-slate-900">{value}</p>
            </div>
          ))}
        </div>
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Warnings</h3>
          {warnings.length ? (
            <ul className="mt-2 space-y-2">
              {warnings.slice(0, 5).map((warning, index) => (
                <li key={`${warning}-${index}`} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  {warning}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">No parsing warnings reported.</p>
          )}
        </div>
        {pageProfiles.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Page Quality</h3>
            <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {pageProfiles.slice(0, 12).map((profile, index) => {
                const profileWarnings = asArray(profile.warnings).filter((warning): warning is string => typeof warning === "string");
                return (
                  <div key={`${profile.page_number ?? index}`} className="rounded-md border border-slate-200 bg-white p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-slate-900">Page {String(profile.page_number ?? index + 1)}</span>
                      <span className={cn("rounded-full px-2 py-0.5 text-xs", profile.needs_ocr ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700")}>
                        {profile.needs_ocr ? "Needs OCR" : "Text OK"}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
                      <span>{String(profile.word_count ?? 0)} words</span>
                      <span>{String(profile.block_count ?? 0)} blocks</span>
                      <span>{String(profile.image_block_count ?? 0)} image blocks</span>
                      <span>{asString(profile.extraction_method, "Unknown")}</span>
                    </div>
                    {profileWarnings.length > 0 && (
                      <p className="mt-2 text-xs text-amber-700">{profileWarnings.slice(0, 2).join(", ")}</p>
                    )}
                  </div>
                );
              })}
            </div>
            {pageProfiles.length > 12 && (
              <p className="mt-2 text-xs text-slate-500">Showing first 12 of {pageProfiles.length} page profiles.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PreviewPanel({
  document,
  fileUrl,
  fileText,
  isFileLoading,
  quality,
  formatBytes,
  formatDate,
  initialFullscreen = false
}: {
  document: DocumentRead;
  fileUrl: string | null;
  fileText: string | undefined;
  isFileLoading: boolean;
  quality: Record<string, unknown> | null;
  formatBytes: (bytes: number) => string;
  formatDate: (dateString: string) => string;
  initialFullscreen?: boolean;
}) {
  const [isFullscreenOpen, setIsFullscreenOpen] = useState(false);
  const [showFullText, setShowFullText] = useState(false);
  const isPdf = document.source_type === "pdf";
  const isImage = document.source_type === "image";
  const isTxt = document.source_type === "txt";
  const isMarkdown = document.source_type === "markdown";
  const isEpub = document.source_type === "epub" || document.mime_type === "application/epub+zip";
  const canFullscreen = isPdf || isTxt || isMarkdown || isImage || isEpub;
  const content = fileText ?? "";
  const TRUNCATE_LENGTH = 5000;
  const isLongText = content.length > TRUNCATE_LENGTH;
  const displayText = showFullText || !isLongText ? content : content.slice(0, TRUNCATE_LENGTH);
  const textLength = (document.cleaned_text || document.parsed_text || "").length;
  const parserEngine = asString(quality?.parser_engine, "Not available");

  useEffect(() => {
    if (!isFullscreenOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsFullscreenOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreenOpen]);

  useEffect(() => {
    if (initialFullscreen && canFullscreen && fileUrl) {
      setIsFullscreenOpen(true);
    }
  }, [canFullscreen, fileUrl, initialFullscreen]);

  const handleOpenOriginal = () => {
    if (fileUrl) {
      window.open(fileUrl, "_blank", "noopener,noreferrer");
    }
  };

  const handleDownloadOriginal = () => {
    if (!fileUrl) return;
    const anchor = window.document.createElement("a");
    anchor.href = fileUrl;
    anchor.download = document.original_filename;
    anchor.click();
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</p>
            <p className="mt-1 font-medium">{getStatusText(document.status)}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">File</p>
            <p className="mt-1 font-medium capitalize">{document.source_type} · {formatBytes(document.file_size)}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Uploaded</p>
            <p className="mt-1 text-sm">{formatDate(document.uploaded_at)}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Parsed Text</p>
            <p className="mt-1 font-medium">{textLength ? `${textLength.toLocaleString()} characters` : "Not available"}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Parser</p>
            <p className="mt-1 font-medium">{parserEngine}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-slate-200 pb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              {isImage ? <ImageIcon className="h-5 w-5 text-blue-600" /> : <FileText className="h-5 w-5 text-blue-600" />}
              <h2 className="font-semibold">Original Preview</h2>
            </div>
            {canFullscreen && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => setIsFullscreenOpen(true)}
              >
                <Maximize2 className="h-4 w-4" />
                Fullscreen
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {isFileLoading ? (
            <div className="flex min-h-[520px] items-center justify-center bg-slate-50 text-sm text-slate-500">
              Loading original file...
            </div>
          ) : isPdf && fileUrl ? (
            <iframe
              src={fileUrl}
              title={document.original_filename}
              className="h-[72vh] min-h-[640px] w-full rounded-b-lg border-0 bg-slate-100"
            />
          ) : isImage && fileUrl ? (
            <div className="flex min-h-[520px] items-center justify-center bg-slate-50 p-4">
              <img
                src={fileUrl}
                alt={document.original_filename}
                className="max-h-[72vh] w-full object-contain"
              />
            </div>
          ) : isEpub && fileUrl ? (
            <EpubReader title={document.title} fileUrl={fileUrl} progressKey={`document-epub-progress-${document.id}`} />
          ) : isTxt && fileText !== undefined ? (
            <div className="max-h-[72vh] min-h-[640px] overflow-y-auto">
              <pre className="whitespace-pre-wrap p-6 text-sm leading-6 text-slate-700">
                {displayText}
              </pre>
              {isLongText && (
                <div className="flex justify-center border-t border-slate-200 bg-slate-50 px-6 py-3">
                  <Button size="sm" variant="outline" onClick={() => setShowFullText((cur) => !cur)}>
                    {showFullText ? "Collapse" : "Show full text"}
                  </Button>
                </div>
              )}
            </div>
          ) : isMarkdown && fileText !== undefined ? (
            <div className="max-h-[72vh] min-h-[640px] overflow-y-auto">
              <div className="prose max-w-none p-6">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayText}</ReactMarkdown>
              </div>
              {isLongText && (
                <div className="flex justify-center border-t border-slate-200 bg-slate-50 px-6 py-3">
                  <Button size="sm" variant="outline" onClick={() => setShowFullText((cur) => !cur)}>
                    {showFullText ? "Collapse" : "Show full text"}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 bg-slate-50 p-8 text-center">
              <FileText className="h-10 w-10 text-slate-300" />
              <div>
                <p className="font-medium text-slate-900">暂不支持此类型的在线预览。</p>
                <p className="mt-1 text-sm text-slate-500">可以打开原文件、下载，或查看文件信息和任务状态。</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {isFullscreenOpen && canFullscreen && (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-slate-950"
          role="dialog"
          aria-modal="true"
          aria-label={`Fullscreen preview for ${document.original_filename}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-slate-950 px-4 py-3 text-white shadow-lg">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{document.original_filename}</p>
              <p className="text-xs text-slate-400">Original {isPdf ? "PDF" : isTxt ? "text" : isImage ? "image" : isEpub ? "EPUB" : "Markdown"} preview</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="border-white/20 bg-white/10 text-white hover:bg-white/20 hover:text-white"
                onClick={handleOpenOriginal}
              >
                <ExternalLink className="h-4 w-4" />
                Open original
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="border-white/20 bg-white/10 text-white hover:bg-white/20 hover:text-white"
                onClick={handleDownloadOriginal}
              >
                <Download className="h-4 w-4" />
                Download original
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="border-white/20 bg-white/10 text-white hover:bg-white/20 hover:text-white"
                onClick={() => setIsFullscreenOpen(false)}
              >
                <X className="h-4 w-4" />
                Close
              </Button>
            </div>
          </div>
          {isPdf ? (
            <iframe
              src={fileUrl ?? undefined}
              title={`Fullscreen preview: ${document.original_filename}`}
              className="min-h-0 flex-1 border-0 bg-slate-100"
            />
          ) : isImage && fileUrl ? (
            <div className="min-h-0 flex-1 overflow-auto bg-slate-950 p-6">
              <img src={fileUrl} alt={document.original_filename} className="mx-auto max-h-full max-w-full object-contain" />
            </div>
          ) : isEpub && fileUrl ? (
            <div className="min-h-0 flex-1 bg-white">
              <EpubReader title={document.title} fileUrl={fileUrl} progressKey={`document-epub-progress-${document.id}`} heightClassName="h-[calc(100vh-4rem)] min-h-0" />
            </div>
          ) : isTxt ? (
            <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap p-6 text-sm leading-6 text-white">
              {content}
            </pre>
          ) : (
            <div className="prose prose-invert min-h-0 flex-1 max-w-none overflow-y-auto p-6">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function chunkHeading(metadata: Record<string, unknown> | null) {
  if (!metadata) return null;
  if (typeof metadata.heading === "string") return metadata.heading;
  if (Array.isArray(metadata.section_path) && metadata.section_path.length > 0) {
    return metadata.section_path.join(" / ");
  }
  return null;
}

function ChunksPanel({
  status,
  chunks,
  isLoading,
  expandedChunks,
  onToggleChunk
}: {
  status: DocumentStatus;
  chunks: DocumentChunk[];
  isLoading: boolean;
  expandedChunks: Set<number>;
  onToggleChunk: (chunkId: number) => void;
}) {
  const [filter, setFilter] = useState<"all" | "ocr" | "table" | "warnings" | "bbox" | "embedded">("all");
  const chunkDetails = chunks.map((chunk) => {
    const metadata = parseChunkMetadata(chunk);
    const invalidMetadata = Boolean(chunk.metadata_json && !metadata);
    const warnings = metadataWarnings(metadata);
    const bboxAvailable = hasBBox(metadata);
    const extractor = asString(metadata?.extractor, "Unknown");
    const ocrUsed = metadata?.ocr_used === true;
    const hasEmbedding = Boolean(chunk.embedding_model);
    return { chunk, metadata, invalidMetadata, warnings, bboxAvailable, extractor, ocrUsed, hasEmbedding };
  });
  const filteredChunks = chunkDetails.filter(({ chunk, warnings, bboxAvailable, ocrUsed, hasEmbedding }) => {
    if (filter === "ocr") return ocrUsed || chunk.chunk_type === "ocr_text" || chunk.chunk_type === "ocr";
    if (filter === "table") return chunk.chunk_type === "table";
    if (filter === "warnings") return warnings.length > 0;
    if (filter === "bbox") return bboxAvailable;
    if (filter === "embedded") return hasEmbedding;
    return true;
  });
  const filters = [
    { id: "all" as const, label: "All", count: chunkDetails.length },
    { id: "ocr" as const, label: "OCR chunks", count: chunkDetails.filter((item) => item.ocrUsed || item.chunk.chunk_type === "ocr_text" || item.chunk.chunk_type === "ocr").length },
    { id: "table" as const, label: "Table chunks", count: chunkDetails.filter((item) => item.chunk.chunk_type === "table").length },
    { id: "warnings" as const, label: "Warning chunks", count: chunkDetails.filter((item) => item.warnings.length > 0).length },
    { id: "bbox" as const, label: "With bbox", count: chunkDetails.filter((item) => item.bboxAvailable).length },
    { id: "embedded" as const, label: "Embedded", count: chunkDetails.filter((item) => item.hasEmbedding).length }
  ];

  if (status === "pending" || status === "processing") {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-slate-600">
          Document is still processing. Chunks will appear after parsing completes.
        </CardContent>
      </Card>
    );
  }
  if (status === "failed") {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-slate-600">
          Parsing failed. No chunks available.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="border-b border-slate-200 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-blue-600" />
            <h2 className="font-semibold">Chunks</h2>
          </div>
          <span className="text-sm text-slate-500">{filteredChunks.length} of {chunks.length} chunks</span>
        </div>
      </CardHeader>
      <CardContent className="p-6">
        {isLoading ? (
          <p className="text-sm text-slate-500">Loading chunks...</p>
        ) : chunks.length === 0 ? (
          <p className="text-sm text-slate-500">No chunks were generated for this document.</p>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 pb-4">
              <Filter className="h-4 w-4 text-slate-400" />
              {filters.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setFilter(item.id)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium",
                    filter === item.id
                      ? "border-blue-200 bg-blue-50 text-blue-700"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  )}
                >
                  {item.label} · {item.count}
                </button>
              ))}
            </div>
            {filteredChunks.length === 0 ? (
              <p className="text-sm text-slate-500">No chunks match this filter.</p>
            ) : filteredChunks.map(({ chunk, metadata, invalidMetadata, warnings, bboxAvailable, extractor, ocrUsed, hasEmbedding }) => {
              const heading = chunkHeading(metadata);
              const expanded = expandedChunks.has(chunk.id);
              const text = chunk.cleaned_text || chunk.text;
              return (
                <div key={chunk.id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span className="font-semibold text-slate-900">Chunk #{chunk.chunk_index}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-slate-700">
                      {chunk.chunk_type}
                    </span>
                    <span className="rounded-full bg-blue-50 px-2 py-1 font-medium text-blue-700">
                      {extractor}
                    </span>
                    <span className={cn("rounded-full px-2 py-1 font-medium", ocrUsed ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700")}>
                      OCR {ocrUsed ? "true" : "false"}
                    </span>
                    <span className={cn("rounded-full px-2 py-1 font-medium", bboxAvailable ? "bg-indigo-50 text-indigo-700" : "bg-slate-50 text-slate-600")}>
                      BBox {bboxAvailable ? "yes" : "no"}
                    </span>
                    {hasEmbedding && (
                      <span className="rounded-full bg-purple-50 px-2 py-1 font-medium text-purple-700">
                        Embedded
                      </span>
                    )}
                    <span>{chunk.token_count ?? 0} tokens</span>
                    <span>{pageRangeLabel(chunk)}</span>
                    {heading && <span className="text-slate-700">{heading}</span>}
                  </div>
                  {bboxAvailable && (
                    <div className="mt-3 flex items-center gap-2 rounded-md border border-indigo-100 bg-indigo-50 px-3 py-2 text-xs text-indigo-700">
                      <MapPin className="h-3.5 w-3.5" />
                      Source location available. PDF highlight preview is planned for a later pass.
                    </div>
                  )}
                  {warnings.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {warnings.slice(0, 3).map((warning, index) => (
                        <span key={`${warning}-${index}`} className="rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">
                          {warning}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">
                    {expanded ? text : `${text.slice(0, 360)}${text.length > 360 ? "..." : ""}`}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    {text.length > 360 && (
                      <Button size="sm" variant="outline" onClick={() => onToggleChunk(chunk.id)}>
                        {expanded ? "Collapse" : "Expand"}
                      </Button>
                    )}
                    {invalidMetadata && (
                      <details className="text-xs text-red-600">
                        <summary className="cursor-pointer font-medium">Invalid metadata</summary>
                        <pre className="mt-2 max-w-full overflow-x-auto rounded bg-red-50 p-2">
                          {chunk.metadata_json}
                        </pre>
                      </details>
                    )}
                    {metadata && (
                      <details className="text-xs text-slate-500">
                        <summary className="cursor-pointer font-medium text-slate-600">Metadata</summary>
                        <pre className="mt-2 max-w-full overflow-x-auto rounded bg-slate-50 p-2">
                          {JSON.stringify(metadata, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function DocumentDetailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const documentId = id ? parseInt(id, 10) : 0;
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("preview");
  const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set());

  const { data, isLoading, error } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId),
    enabled: documentId > 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 2000 : false;
    }
  });
  const { data: kgData, isLoading: isKgLoading } = useQuery({
    queryKey: ["document", documentId, "kg"],
    queryFn: () => getDocumentKg(documentId),
    enabled: documentId > 0 && activeTab === "diagnostics" && isDoneStatus(data?.status) && data?.source_type !== "image"
  });
  const { data: chunks = [], isLoading: isChunksLoading } = useQuery({
    queryKey: ["document", documentId, "chunks"],
    queryFn: () => getDocumentChunks(documentId),
    enabled: documentId > 0 && isDoneStatus(data?.status)
  });
  const { data: fileBlob, isLoading: isFileLoading } = useQuery({
    queryKey: ["document", documentId, "file"],
    queryFn: () => getDocumentFileBlob(documentId),
    enabled: documentId > 0 && Boolean(data) && data?.status !== "deleted",
  });
  const { data: fileText, isLoading: isFileTextLoading } = useQuery({
    queryKey: ["document", documentId, "file-text"],
    queryFn: () => getDocumentFileText(documentId),
    enabled: documentId > 0 && Boolean(data) && data?.status !== "deleted"
      && (data?.source_type === "txt" || data?.source_type === "markdown"),
  });
  const [fileUrl, setFileUrl] = useState<string | null>(null);

  const retryMutation = useMutation({
    mutationFn: retryDocumentParse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  const reEmbedMutation = useMutation({
    mutationFn: reEmbedDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      queryClient.invalidateQueries({ queryKey: ["document", documentId, "chunks"] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      navigate("/documents");
    }
  });

  const handleRetry = () => {
    retryMutation.mutate(documentId);
  };

  const handleReEmbed = () => {
    reEmbedMutation.mutate(documentId);
  };

  const handleDelete = () => {
    if (
      confirm(
        "Are you sure you want to delete this document? This action cannot be undone."
      )
    ) {
      deleteMutation.mutate(documentId);
    }
  };

  const handleCopyEvent = (index: number, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const toggleChunk = (chunkId: number) => {
    setExpandedChunks((current) => {
      const next = new Set(current);
      if (next.has(chunkId)) {
        next.delete(chunkId);
      } else {
        next.add(chunkId);
      }
      return next;
    });
  };

  useEffect(() => {
    if (!fileBlob) {
      setFileUrl(null);
      return;
    }

    const objectUrl = URL.createObjectURL(fileBlob);
    setFileUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [fileBlob]);

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
  };

  const formatDate = formatChinaDateTime;

  if (!data) {
    return (
      <div className="space-y-6">
        <Button
          variant="ghost"
          size="sm"
          className="gap-2"
          onClick={() => navigate("/knowledge")}
        >
          <ChevronLeft className="h-4 w-4" />
          Back to Knowledge
        </Button>

        {isLoading && (
          <div className="space-y-4">
            <div className="h-10 w-48 animate-pulse rounded-lg bg-slate-100" />
            <div className="space-y-2">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-4 animate-pulse rounded bg-slate-100" />
              ))}
            </div>
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {error instanceof Error ? error.message : "Failed to load document"}
            </AlertDescription>
          </Alert>
        )}
      </div>
    );
  }

  const document = data;
  const events = data.events || [];
  const quality = parseJsonObject(document.parse_quality_json);
  const tabs = [
    { id: "preview" as const, label: "Preview" },
    { id: "text" as const, label: "Text" },
    { id: "chunks" as const, label: "Chunks" },
    { id: "diagnostics" as const, label: "Diagnostics" },
    { id: "events" as const, label: "Events" }
  ];
  const canUseOriginalFile = Boolean(fileUrl);
  const handleOpenOriginal = () => {
    if (fileUrl) {
      window.open(fileUrl, "_blank", "noopener,noreferrer");
    }
  };
  const handleDownloadOriginal = () => {
    if (!fileUrl) return;
    const anchor = window.document.createElement("a");
    anchor.href = fileUrl;
    anchor.download = document.original_filename;
    anchor.click();
  };

  return (
    <div className="space-y-6">
      <Button
        variant="ghost"
        size="sm"
        className="gap-2"
        onClick={() => navigate("/knowledge")}
      >
        <ChevronLeft className="h-4 w-4" />
        Back to Knowledge
      </Button>

      {/* Header */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{document.title}</h1>
            <p className="mt-2 text-sm text-slate-500">{document.original_filename}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              onClick={handleOpenOriginal}
              disabled={!canUseOriginalFile}
              className="gap-2"
            >
              <ExternalLink className="h-4 w-4" />
              Open original
            </Button>
            <Button
              variant="outline"
              onClick={handleDownloadOriginal}
              disabled={!canUseOriginalFile}
              className="gap-2"
            >
              <Download className="h-4 w-4" />
              Download original
            </Button>
            <Button
              variant="outline"
              onClick={() => navigate(`/notes?documentId=${document.id}`)}
              className="gap-2"
            >
              <BrainCircuit className="h-4 w-4" />
              写文档笔记
            </Button>
            <div className={cn("flex items-center gap-2 rounded-lg border px-3 py-2", getStatusColor(document.status))}>
              {getStatusIcon(document.status)}
              <span className="font-medium">
                {getStatusText(document.status)}
              </span>
            </div>
          </div>
        </div>

        {/* Document Info Card */}
        <Card className="hidden lg:block">
          <CardContent className="grid gap-4 p-6 sm:grid-cols-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                File Size
              </p>
              <p className="mt-1 text-lg font-medium">{formatBytes(document.file_size)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                File Type
              </p>
              <p className="mt-1 capitalize font-medium">{document.source_type}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Uploaded
              </p>
              <p className="mt-1 text-sm">{formatDate(document.uploaded_at)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Processing Mode
              </p>
              <p className="mt-1 font-medium">{processingModeLabel(document.processing_mode)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Processing Strategy
              </p>
              <p className="mt-1 font-medium">{document.processing_strategy ?? "-"}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Latest Job
              </p>
              <p className="mt-1 font-medium">{document.latest_parse_job?.status ?? "-"}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Collection
              </p>
              <p className="mt-1 break-words font-medium">{document.collection_name ?? "-"}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Content Hash
              </p>
              <p className="mt-1 break-all font-mono text-xs">{document.content_hash ?? "-"}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Chunks
              </p>
              <p className="mt-1 font-medium">{document.chunk_count}</p>
            </div>
            <div className="sm:col-span-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Tags
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {document.tags.length ? document.tags.map((tag) => <TagPill key={tag.id} tag={tag} />) : <span className="text-sm text-slate-500">No tags</span>}
              </div>
              <div className="mt-3">
                <TagSelector documentIds={[document.id]} compact />
                <p className="mt-2 text-xs text-slate-500">当前后端支持添加/应用标签；移除单个文档标签需要后端补充最小接口。</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Status Messages */}
        {(document.status === "pending" || document.status === "processing") && (
          <Alert className="border-yellow-200 bg-yellow-50 text-yellow-800">
            <Clock className="h-4 w-4" />
            <AlertDescription>
              Processing is not complete yet. This page will refresh automatically.
              {document.latest_parse_job ? ` Latest job: ${document.latest_parse_job.status}.` : ""}
            </AlertDescription>
          </Alert>
        )}

        {document.status === "failed" && (document.fail_reason || document.error_message) && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              <div>
                <p className="font-medium">Failed to parse document</p>
                <p className="mt-1 text-sm">{document.fail_reason || document.error_message}</p>
              </div>
            </AlertDescription>
          </Alert>
        )}

        {document.parsed_at && (
          <Alert className="border-emerald-200 bg-emerald-50 text-emerald-800">
            <CheckCircle2 className="h-4 w-4" />
            <AlertDescription>
              Processing completed on {formatDate(document.parsed_at)}
            </AlertDescription>
          </Alert>
        )}
      </div>

      <div className="flex gap-2 border-b border-slate-200">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "border-b-2 px-3 py-2 text-sm font-medium",
              activeTab === tab.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-slate-500 hover:text-slate-800"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "preview" && (
        <PreviewPanel
          document={document}
          fileUrl={fileUrl}
          fileText={fileText}
          isFileLoading={isFileLoading || isFileTextLoading}
          quality={quality}
          formatBytes={formatBytes}
          formatDate={formatDate}
          initialFullscreen={searchParams.get("fullscreen") === "1"}
        />
      )}

      {activeTab === "text" && (
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-blue-600" />
              <h2 className="font-semibold">Parsed Text</h2>
            </div>
          </CardHeader>
          <CardContent className="space-y-6 p-6">
            <TextPreview
              title="Cleaned Text"
              text={document.cleaned_text}
              copied={copiedIndex === -2}
              onCopy={() => handleCopyEvent(-2, document.cleaned_text || "")}
              emptyMessage="No cleaned text available. Check parsing quality and events."
              previewLength={2800}
            />
            <TextPreview
              title="Extracted Text"
              text={document.parsed_text}
              copied={copiedIndex === -1}
              onCopy={() => handleCopyEvent(-1, document.parsed_text || "")}
              emptyMessage="No extracted text available. Check parsing quality and events."
              previewLength={2200}
            />
            {document.references_text && (
              <TextPreview
                title="References"
                text={document.references_text}
                copied={copiedIndex === -3}
                onCopy={() => handleCopyEvent(-3, document.references_text || "")}
                emptyMessage="No references were separated from this document."
                previewLength={1800}
              />
            )}
          </CardContent>
        </Card>
      )}

      {activeTab === "diagnostics" && (
        <div className="space-y-4">
          <ParsingQualityPanel quality={quality} />
          {isDoneStatus(document.status) && document.source_type !== "image" && (
            <Card>
              <CardHeader className="border-b border-slate-200 pb-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Network className="h-5 w-5 text-slate-500" />
                    <h2 className="font-semibold">Knowledge Graph</h2>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
                      Experimental
                    </span>
                  </div>
                  {kgData ? (
                    <span className="text-sm text-slate-500">
                      {kgData.entities.length} entities · {kgData.relations.length} relations
                    </span>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent className="p-6">
                {isKgLoading ? (
                  <p className="text-sm text-slate-500">Loading graph...</p>
                ) : kgData && kgData.relations.length > 0 ? (
                  <p className="text-sm text-slate-600">
                    Knowledge graph extraction is experimental. {kgData.entities.length} entities and {kgData.relations.length} relations were extracted.
                  </p>
                ) : (
                  <p className="text-sm text-slate-500">
                    Knowledge graph extraction is experimental and is not part of this document preview workflow.
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {activeTab === "chunks" && (
        <ChunksPanel
          status={document.status}
          chunks={chunks}
          isLoading={isChunksLoading}
          expandedChunks={expandedChunks}
          onToggleChunk={toggleChunk}
        />
      )}

      {/* Event Timeline */}
      {activeTab === "events" && events.length > 0 && (
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4">
            <h2 className="font-semibold">Processing Timeline</h2>
          </CardHeader>
          <CardContent className="p-6">
            <div className="space-y-4">
              {events.map((event, index) => (
                <div key={event.id} className="flex gap-4">
                  <div className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-blue-600" />
                  <div className="flex-1 pb-4">
                    <div className="flex items-center justify-between">
                      <p className="font-medium text-slate-900">{event.event_type}</p>
                      <span className="text-xs text-slate-500">
                        {formatDate(event.created_at)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-600">{event.message}</p>
                    {event.event_metadata && (
                      <div className="mt-2 flex items-center gap-2">
                        <code className="max-w-md overflow-x-auto rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
                          {event.event_metadata}
                        </code>
                        <button
                          onClick={() => handleCopyEvent(index, event.event_metadata || "")}
                          className="text-slate-400 hover:text-slate-600"
                          title="Copy metadata"
                        >
                          <Copy className="h-4 w-4" />
                          {copiedIndex === index && (
                            <span className="ml-1 text-xs">Copied!</span>
                          )}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="flex gap-3 border-t border-slate-200 pt-6">
        {document.status === "failed" && (
          <Button
            onClick={handleRetry}
            disabled={retryMutation.isPending}
            className="gap-2"
          >
            {retryMutation.isPending ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Retry Parsing
          </Button>
        )}
        {isDoneStatus(document.status) && (
          <Button
            onClick={handleReEmbed}
            disabled={reEmbedMutation.isPending}
            className="gap-2"
            variant="outline"
          >
            {reEmbedMutation.isPending ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <BrainCircuit className="h-4 w-4" />
            )}
            Re-embed
          </Button>
        )}
        {document.status !== "deleted" && (
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="gap-2"
          >
            {deleteMutation.isPending ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            Delete Document
          </Button>
        )}
      </div>
    </div>
  );
}
