import {
  AlertCircle,
  BrainCircuit,
  CheckCircle2,
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
import { DocumentListItem, DocumentStatus, processingModeLabel } from "@/lib/types";
import { cn } from "@/lib/utils";

function getStatusIcon(status: DocumentStatus) {
  switch (status) {
    case "pending":
    case "processing":
      return <Clock className="h-3.5 w-3.5" />;
    case "done":
    case "completed":
      return <CheckCircle2 className="h-3.5 w-3.5" />;
    case "failed":
      return <AlertCircle className="h-3.5 w-3.5" />;
    case "deleted":
      return <Trash2 className="h-3.5 w-3.5" />;
    default:
      return null;
  }
}

function getStatusText(status: DocumentStatus) {
  switch (status) {
    case "pending": return "等待";
    case "processing": return "解析中";
    case "done":
    case "completed": return "完成";
    case "failed": return "失败";
    case "deleted": return "已删除";
    default: return status;
  }
}

function getStatusColor(status: DocumentStatus) {
  switch (status) {
    case "pending":
    case "processing": return "bg-amber-50 text-amber-700 ring-amber-100";
    case "done":
    case "completed": return "bg-emerald-50 text-emerald-700 ring-emerald-100";
    case "failed": return "bg-red-50 text-red-700 ring-red-100";
    case "deleted": return "bg-slate-50 text-slate-500 ring-slate-100";
    default: return "bg-slate-50 text-slate-600 ring-slate-100";
  }
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, index)).toFixed(1)} ${sizes[index]}`;
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
  const meta = [document.source_type?.toUpperCase(), formatBytes(document.file_size), processingModeLabel(document.processing_mode), document.chunk_count > 0 ? `${document.chunk_count} chunks` : null, document.collection_name ? `集合：${document.collection_name}` : null].filter(Boolean);

  return (
    <article className="group cursor-pointer rounded-2xl border border-slate-100 bg-white px-4 py-3 transition hover:border-slate-200 hover:bg-slate-50/70" onClick={() => navigate(`/documents/${document.id}`)}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-slate-50 text-slate-500 ring-1 ring-slate-100"><FileText className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-slate-900">{document.title}</h3>
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1", getStatusColor(processingStatus))}>{getStatusIcon(processingStatus)}{getStatusText(processingStatus)}</span>
          </div>
          <p className="mt-1 truncate text-xs text-slate-500">{document.original_filename}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
            {meta.map((item) => <span key={String(item)}>{item}</span>)}
            <span>上传于 {formatChinaDateTime(document.created_at)}</span>
          </div>
          {document.tags.length > 0 ? <div className="mt-2 flex flex-wrap gap-1.5">{document.tags.slice(0, 5).map((tag) => <span key={tag.id} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">#{tag.name}</span>)}{document.tags.length > 5 ? <span className="text-xs text-slate-400">+{document.tags.length - 5}</span> : null}</div> : null}
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
