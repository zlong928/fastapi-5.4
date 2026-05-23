import {
  AlertCircle,
  BrainCircuit,
  Clock,
  Eye,
  FileText,
  FolderInput,
  Maximize2,
  RefreshCw,
  Trash2
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { formatChinaDateTime } from "@/lib/time";
import { DocumentListItem, DocumentStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

function shouldShowStatus(status: DocumentStatus | string) {
  return status === "pending" || status === "processing" || status === "failed";
}

function getStatusIcon(status: DocumentStatus | string) {
  switch (status) {
    case "pending":
    case "processing":
      return <Clock className="h-3.5 w-3.5" />;
    case "failed":
      return <AlertCircle className="h-3.5 w-3.5" />;
    default:
      return null;
  }
}

function getStatusText(status: DocumentStatus | string) {
  switch (status) {
    case "pending": return "等待解析";
    case "processing": return "解析中";
    case "failed": return "解析失败";
    default: return status;
  }
}

function getStatusColor(status: DocumentStatus | string) {
  switch (status) {
    case "pending":
    case "processing": return "bg-amber-50 text-amber-700 ring-amber-100";
    case "failed": return "bg-red-50 text-red-700 ring-red-100";
    default: return "bg-slate-50 text-slate-600 ring-slate-100";
  }
}

function sourceTypeLabel(sourceType: string) {
  const labels: Record<string, string> = {
    pdf: "PDF",
    markdown: "Markdown",
    txt: "文本",
    image: "图片",
    epub: "EPUB",
    docx: "Word",
    bookmark: "网页收藏",
    note: "笔记",
    diary: "日记"
  };
  return labels[sourceType] ?? sourceType.toUpperCase();
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, index)).toFixed(1)} ${sizes[index]}`;
}

function formatDocumentTime(document: DocumentListItem) {
  const isNoteLike = document.source_type === "note" || document.source_type === "diary";
  const timestamp = isNoteLike ? document.updated_at : document.uploaded_at || document.created_at;
  return `${isNoteLike ? "更新于" : "上传于"} ${formatChinaDateTime(timestamp)}`;
}

interface DocumentCardProps {
  document: DocumentListItem;
  onRetry?: (id: number) => void;
  onDelete?: (id: number) => void;
  onMoveToCollection?: (document: DocumentListItem) => void;
  isRetrying?: boolean;
  isDeleting?: boolean;
}

export function DocumentCard({ document, onRetry, onDelete, onMoveToCollection, isRetrying, isDeleting }: DocumentCardProps) {
  const navigate = useNavigate();
  const processingStatus = document.processing_status ?? document.status;
  const processingError = document.processing_error ?? document.fail_reason ?? document.error_message;
  const meta = [sourceTypeLabel(document.source_type), formatBytes(document.file_size), formatDocumentTime(document)].filter(Boolean);
  const isIndexed = document.chunk_count > 0;

  return (
    <article className="group cursor-pointer rounded-2xl border border-slate-100 bg-white px-4 py-3 transition hover:border-slate-200 hover:bg-slate-50/70" onClick={() => navigate(`/documents/${document.id}`)}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-slate-50 text-slate-500 ring-1 ring-slate-100"><FileText className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-slate-900">{document.title}</h3>
            {shouldShowStatus(processingStatus) ? <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1", getStatusColor(processingStatus))}>{getStatusIcon(processingStatus)}{getStatusText(processingStatus)}</span> : null}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
            {meta.map((item) => <span key={String(item)}>{item}</span>)}
            {isIndexed ? <span>已索引</span> : null}
          </div>
          {document.content_summary ? <p className="mt-2 line-clamp-1 text-sm text-slate-500">{document.content_summary}</p> : <p className="mt-2 truncate text-xs text-slate-400">{document.original_filename}</p>}
          {(document.tags.length > 0 || document.collection_name) ? <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {document.collection_name ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">集合：{document.collection_name}</span> : null}
            {document.tags.slice(0, 5).map((tag) => <span key={tag.id} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">#{tag.name}</span>)}
            {document.tags.length > 5 ? <span className="text-xs text-slate-400">+{document.tags.length - 5}</span> : null}
          </div> : null}
          {processingStatus === "failed" && processingError ? <p className="mt-2 line-clamp-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{processingError}</p> : null}
        </div>
        <div className="flex shrink-0 items-center gap-1 opacity-100 md:opacity-0 md:transition md:group-hover:opacity-100" onClick={(event) => event.stopPropagation()}>
          <Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" onClick={() => navigate(`/documents/${document.id}`)} title="预览"><Eye className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" onClick={() => navigate(`/documents/${document.id}?fullscreen=1`)} title="全屏预览"><Maximize2 className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" onClick={() => navigate(`/notes?documentId=${document.id}`)} title="关联笔记"><BrainCircuit className="h-4 w-4" /></Button>
          {onMoveToCollection ? <Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" onClick={() => onMoveToCollection(document)} title="移动到集合"><FolderInput className="h-4 w-4" /></Button> : null}
          {processingStatus === "failed" ? <Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" onClick={() => onRetry?.(document.id)} disabled={isRetrying} title="重新解析"><RefreshCw className={cn("h-4 w-4", isRetrying && "animate-spin")} /></Button> : null}
          {processingStatus !== "deleted" ? <Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0 text-red-500 hover:text-red-600" onClick={() => onDelete?.(document.id)} disabled={isDeleting} title="删除文档"><Trash2 className="h-4 w-4" /></Button> : null}
        </div>
      </div>
    </article>
  );
}
