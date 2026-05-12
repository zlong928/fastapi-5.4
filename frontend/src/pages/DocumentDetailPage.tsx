import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  Copy,
  RefreshCw,
  Trash2,
  Clock,
  Download
} from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { deleteDocument, getDocument, retryDocumentParse } from "@/lib/api";
import { DocumentStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

function getStatusIcon(status: DocumentStatus) {
  switch (status) {
    case "pending":
    case "processing":
      return <Clock className="h-5 w-5 text-yellow-600" />;
    case "parsed":
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
    case "parsed":
      return "Parsed";
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
    case "parsed":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "failed":
      return "bg-red-50 text-red-700 border-red-200";
    case "deleted":
      return "bg-slate-50 text-slate-600 border-slate-200";
    default:
      return "bg-slate-50 text-slate-600 border-slate-200";
  }
}

export function DocumentDetailPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const documentId = id ? parseInt(id, 10) : 0;
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId),
    enabled: documentId > 0
  });

  const retryMutation = useMutation({
    mutationFn: retryDocumentParse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document", documentId] });
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

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(date);
  };

  if (!data) {
    return (
      <div className="space-y-6">
        <Button
          variant="ghost"
          size="sm"
          className="gap-2"
          onClick={() => navigate("/documents")}
        >
          <ChevronLeft className="h-4 w-4" />
          Back to Documents
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

  return (
    <div className="space-y-6">
      <Button
        variant="ghost"
        size="sm"
        className="gap-2"
        onClick={() => navigate("/documents")}
      >
        <ChevronLeft className="h-4 w-4" />
        Back to Documents
      </Button>

      {/* Header */}
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{document.title}</h1>
            <p className="mt-2 text-sm text-slate-500">{document.original_filename}</p>
          </div>
          <div className={cn("flex items-center gap-2 rounded-lg border px-3 py-2", getStatusColor(document.status))}>
            {getStatusIcon(document.status)}
            <span className="font-medium">{getStatusText(document.status)}</span>
          </div>
        </div>

        {/* Document Info Card */}
        <Card>
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
          </CardContent>
        </Card>

        {/* Status Messages */}
        {document.status === "processing" && (
          <Alert className="border-yellow-200 bg-yellow-50 text-yellow-800">
            <Clock className="h-4 w-4" />
            <AlertDescription>
              Your document is being processed. Please check back in a moment.
            </AlertDescription>
          </Alert>
        )}

        {document.status === "failed" && document.error_message && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              <div>
                <p className="font-medium">Failed to parse document</p>
                <p className="mt-1 text-sm">{document.error_message}</p>
              </div>
            </AlertDescription>
          </Alert>
        )}

        {document.parsed_at && (
          <Alert className="border-emerald-200 bg-emerald-50 text-emerald-800">
            <CheckCircle2 className="h-4 w-4" />
            <AlertDescription>
              Successfully parsed on {formatDate(document.parsed_at)}
            </AlertDescription>
          </Alert>
        )}
      </div>

      {/* Parsed Text Preview */}
      {document.parsed_text && (
        <Card>
          <CardHeader className="border-b border-slate-200 pb-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Extracted Text</h2>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleCopyEvent(-1, document.parsed_text || "")}
                className="gap-2"
              >
                <Copy className="h-4 w-4" />
                {copiedIndex === -1 ? "Copied!" : "Copy"}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-6">
            <div className="max-h-96 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-4">
              <pre className="whitespace-pre-wrap text-sm text-slate-700">
                {document.parsed_text.substring(0, 2000)}
                {document.parsed_text.length > 2000 && "..."}
              </pre>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {document.parsed_text.length} characters extracted
            </p>
          </CardContent>
        </Card>
      )}

      {/* Event Timeline */}
      {events.length > 0 && (
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
