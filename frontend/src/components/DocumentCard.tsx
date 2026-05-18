import { AlertCircle, CheckCircle2, Clock, HardDrive, Trash2, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatChinaDateTime } from "@/lib/time";
import { DocumentListItem, DocumentStatus, processingModeLabel } from "@/lib/types";
import { cn } from "@/lib/utils";

function getStatusIcon(status: DocumentStatus) {
  switch (status) {
    case "pending":
    case "processing":
      return <Clock className="h-4 w-4 text-yellow-600" />;
    case "done":
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
    case "failed":
      return <AlertCircle className="h-4 w-4 text-red-600" />;
    case "deleted":
      return <Trash2 className="h-4 w-4 text-slate-400" />;
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
      return "bg-yellow-50 text-yellow-700";
    case "done":
    case "completed":
      return "bg-emerald-50 text-emerald-700";
    case "failed":
      return "bg-red-50 text-red-700";
    case "deleted":
      return "bg-slate-50 text-slate-600";
    default:
      return "bg-slate-50 text-slate-600";
  }
}

interface DocumentCardProps {
  document: DocumentListItem;
  onRetry?: (id: number) => void;
  onDelete?: (id: number) => void;
  isRetrying?: boolean;
  isDeleting?: boolean;
}

export function DocumentCard({
  document,
  onRetry,
  onDelete,
  isRetrying,
  isDeleting
}: DocumentCardProps) {
  const navigate = useNavigate();
  const processingStatus = document.processing_status ?? document.status;
  const processingError = document.processing_error ?? document.fail_reason ?? document.error_message;
  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
  };

  return (
    <Card
      className="cursor-pointer transition-all hover:shadow-md"
      onClick={() => navigate(`/documents/${document.id}`)}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900 truncate">
                {document.title}
              </h3>
              <div className={cn("flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium", getStatusColor(processingStatus))}>
                {getStatusIcon(processingStatus)}
                {getStatusText(processingStatus)}
              </div>
            </div>
            <p className="mt-1 text-sm text-slate-500 truncate">
              {document.original_filename}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-500">
              <div className="flex items-center gap-1">
                <HardDrive className="h-3.5 w-3.5" />
                {formatBytes(document.file_size)}
              </div>
              <div className="capitalize text-slate-600">
                {document.source_type}
              </div>
              <div className="text-slate-600">
                {processingModeLabel(document.processing_mode)}
              </div>
              <div>
                Uploaded {formatChinaDateTime(document.created_at)}
              </div>
              {document.parsed_at && document.source_type !== "image" && (
                <div>
                  Completed {formatChinaDateTime(document.parsed_at)}
                </div>
              )}
              {document.latest_parse_job_status && (
                <div>
                  Job {document.latest_parse_job_status}
                </div>
              )}
              {document.content_hash && (
                <div>
                  Hash {document.content_hash.slice(0, 12)}
                </div>
              )}
              {document.collection_name && (
                <div>
                  {document.collection_name}
                </div>
              )}
              {document.chunk_count > 0 && (
                <div>
                  {document.chunk_count} chunks
                </div>
              )}
            </div>
            {document.tags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {document.tags.map((tag) => (
                  <span key={tag.id} className="rounded-full bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
                    {tag.name}
                  </span>
                ))}
              </div>
            )}
            {processingStatus === "failed" && processingError && (
              <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                {processingError}
              </p>
            )}
          </div>
          <div className="flex flex-shrink-0 gap-2" onClick={(e) => e.stopPropagation()}>
            {processingStatus === "failed" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onRetry?.(document.id)}
                disabled={isRetrying}
                title="Retry parsing"
              >
                {isRetrying ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
              </Button>
            )}
            {processingStatus !== "deleted" && (
              <Button
                size="sm"
                variant="outline"
                className="text-red-600 hover:text-red-700"
                onClick={() => onDelete?.(document.id)}
                disabled={isDeleting}
                title="Delete document"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
