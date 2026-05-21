import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileUp, Loader2, X } from "lucide-react";
import { DragEvent, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getDocumentProcessingStatus, uploadDocument } from "@/lib/api";
import { DOCUMENT_PROCESSING_MODE_OPTIONS, DocumentProcessingMode, DocumentStatus, DocumentUploadResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

type UploadItem = {
  id: string;
  name: string;
  title?: string;
  status: "uploading" | "success" | "failed";
  progress: number;
  document?: DocumentUploadResponse;
  error?: string;
};

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const MAX_UPLOAD_MB = Math.round(MAX_UPLOAD_BYTES / 1024 / 1024);
const SUPPORTED_EXTENSIONS = [".pdf", ".md", ".markdown", ".txt", ".png", ".jpg", ".jpeg", ".webp"];
const SUPPORTED_MIME_TYPES = [
  "application/pdf",
  "text/markdown",
  "text/plain",
  "image/png",
  "image/jpeg",
  "image/webp"
];

function isSupportedFile(file: File) {
  const lowerName = file.name.toLowerCase();
  return SUPPORTED_MIME_TYPES.includes(file.type) || SUPPORTED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
}

function isTerminalDocumentStatus(status?: DocumentStatus | string | null) {
  return status === "done" || status === "completed" || status === "failed" || status === "deleted";
}

function UploadProcessingStatus({ documentId, initialStatus }: { documentId: number; initialStatus?: DocumentStatus }) {
  const statusQuery = useQuery({
    queryKey: ["document-processing-status", documentId],
    queryFn: () => getDocumentProcessingStatus(documentId),
    initialData: initialStatus
      ? {
          document_id: documentId,
          status: initialStatus,
          processing_status: initialStatus,
          created_at: "",
          updated_at: ""
        }
      : undefined,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return isTerminalDocumentStatus(status) ? false : 2000;
    }
  });

  const status = statusQuery.data?.status ?? initialStatus ?? "pending";
  const processingError = statusQuery.data?.processing_error ?? statusQuery.data?.error;
  const chunkCount = statusQuery.data?.chunk_count;

  return (
    <div className="mt-2 rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <div className="flex flex-wrap items-center gap-2">
        <span>Processing status:</span>
        <span className="font-semibold capitalize text-slate-900">{status}</span>
        {!isTerminalDocumentStatus(status) ? <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-600" /> : null}
        {typeof chunkCount === "number" ? <span className="text-slate-500">Chunks: {chunkCount}</span> : null}
      </div>
      {processingError ? <p className="mt-1 text-red-600">{processingError}</p> : null}
    </div>
  );
}

export function DocumentUploader() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [isDragging, setIsDragging] = useState(false);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [customTitle, setCustomTitle] = useState("");
  const [processingMode, setProcessingMode] = useState<DocumentProcessingMode>("auto");
  const selectedMode = DOCUMENT_PROCESSING_MODE_OPTIONS.find((option) => option.value === processingMode);

  const mutation = useMutation({
    mutationFn: async (files: File[]) => {
      const uploaded: UploadItem[] = [];
      for (const file of files) {
        const id = `${Date.now()}-${Math.random()}`;
        setItems((current) => [...current, { id, name: file.name, status: "uploading", progress: 0 }]);
        try {
          const document = await uploadDocument(file, customTitle || undefined, processingMode, (progress) => {
            setItems((current) =>
              current.map((item) => (item.id === id ? { ...item, progress } : item))
            );
          });
          uploaded.push({ id, name: file.name, status: "success", progress: 100, document });
          setItems((current) =>
            current.map((item) =>
              item.id === id ? { id, name: file.name, status: "success", progress: 100, document } : item
            )
          );
        } catch (error) {
          const message = error instanceof Error ? error.message : "Upload failed";
          uploaded.push({ id, name: file.name, status: "failed", progress: 0, error: message });
          setItems((current) =>
            current.map((item) =>
              item.id === id ? { id, name: file.name, status: "failed", progress: item.progress, error: message } : item
            )
          );
        }
      }
      setCustomTitle("");
      return uploaded;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  function uploadFiles(fileList: FileList | File[]) {
    const rejected: UploadItem[] = [];
    const files = Array.from(fileList).filter((file) => {
      if (file.size > MAX_UPLOAD_BYTES) {
        rejected.push({
          id: `size-${file.name}-${Date.now()}`,
          name: file.name,
          status: "failed",
          progress: 0,
          error: `File exceeds the ${MAX_UPLOAD_MB} MB limit.`
        });
        return false;
      }
      if (!isSupportedFile(file)) {
        rejected.push({
          id: `type-${file.name}-${Date.now()}`,
          name: file.name,
          status: "failed",
          progress: 0,
          error: "Please choose PDF, Markdown, text, PNG, JPG, JPEG, or WebP files."
        });
        return false;
      }
      return true;
    });

    if (!files.length) {
      setItems(rejected.length ? rejected : [
        {
          id: `error-${Date.now()}`,
          name: "No supported files selected",
          status: "failed",
          progress: 0,
          error: "Please choose PDF, Markdown, text, PNG, JPG, JPEG, or WebP files."
        }
      ]);
      return;
    }
    if (rejected.length) {
      setItems((current) => [...current, ...rejected]);
    }
    mutation.mutate(files);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    uploadFiles(event.dataTransfer.files);
  }

  function clearItems() {
    setItems([]);
  }

  function removeItem(id: string) {
    setItems((current) => current.filter((item) => item.id !== id));
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(260px,360px)]">
        <div>
          <label className="block text-sm font-medium text-slate-700">
            Document title (optional)
          </label>
          <input
            type="text"
            value={customTitle}
            onChange={(e) => setCustomTitle(e.target.value)}
            placeholder="e.g., My Research Paper"
            disabled={mutation.isPending}
            className="mt-2 block w-full rounded-lg border border-slate-300 px-4 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
          />
          <p className="mt-1 text-xs text-slate-500">
            If not provided, the filename will be used as the title.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">
            Processing mode
          </label>
          <select
            value={processingMode}
            onChange={(event) => setProcessingMode(event.target.value as DocumentProcessingMode)}
            disabled={mutation.isPending}
            className="mt-2 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
          >
            {DOCUMENT_PROCESSING_MODE_OPTIONS.filter((option) => !option.advanced).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
            <optgroup label="Advanced tools">
              {DOCUMENT_PROCESSING_MODE_OPTIONS.filter((option) => option.advanced).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          </select>
          <p className="mt-1 text-xs text-slate-500">{selectedMode?.description}</p>
        </div>
      </div>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={cn(
          "rounded-lg border-2 border-dashed bg-card p-10 text-center shadow-soft transition",
          isDragging ? "border-blue-400 bg-blue-50" : "border-slate-300"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp,application/pdf,text/markdown,text/plain,image/png,image/jpeg,image/webp"
          multiple
          disabled={mutation.isPending}
          className="hidden"
          onChange={(event) => event.target.files && uploadFiles(event.target.files)}
        />
        <FileUp className="mx-auto h-10 w-10 text-slate-500" />
        <h2 className="mt-4 text-lg font-semibold">Drop files here</h2>
        <p className="mt-2 text-sm text-slate-500">
          Supports PDF, Markdown, text, PNG, JPG, JPEG, and WebP up to {MAX_UPLOAD_MB} MB each
        </p>
        <Button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={mutation.isPending}
          className="mt-6"
        >
          Select Files
        </Button>
      </div>

      {items.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Upload Status
            </h3>
            <Button
              variant="outline"
              size="sm"
              onClick={clearItems}
              className="text-xs"
            >
              Clear All
            </Button>
          </div>

          {items.map((item) => (
            <div key={item.id} className="relative">
              {item.status === "failed" ? (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription className="flex-1">
                    <span className="font-medium">{item.name}</span>
                    <span className="block">{item.error ?? "Upload failed"}</span>
                  </AlertDescription>
                  <button
                    onClick={() => removeItem(item.id)}
                    className="ml-4 text-destructive hover:opacity-70"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </Alert>
              ) : (
                <Card>
                  <CardContent className="flex items-start gap-3 p-4">
                    {item.status === "uploading" ? (
                      <Loader2 className="mt-0.5 h-5 w-5 flex-shrink-0 animate-spin text-blue-600" />
                    ) : (
                      <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-600" />
                    )}
                    <div className="flex-1">
                      <p className="font-medium">{item.name}</p>
                      {item.document && (
                        <p className="text-sm text-slate-500">
                          Upload status: <span className="capitalize">{item.document.status}</span>
                          <span className="ml-2">Mode: {selectedMode?.label}</span>
                        </p>
                      )}
                      {item.document ? (
                        <UploadProcessingStatus documentId={item.document.document_id} initialStatus={item.document.status} />
                      ) : null}
                      {item.status === "success" && (
                        <div className="mt-2">
                          <div className="flex items-center justify-between text-xs text-slate-500">
                            <span>Upload complete</span>
                            <span>100%</span>
                          </div>
                          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                            <div className="h-full rounded-full bg-emerald-600" style={{ width: "100%" }} />
                          </div>
                        </div>
                      )}
                      {item.status === "uploading" && (
                        <div className="mt-2">
                          <div className="flex items-center justify-between text-sm text-slate-500">
                            <span>Uploading...</span>
                            <span>{item.progress}%</span>
                          </div>
                          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                            <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${item.progress}%` }} />
                          </div>
                        </div>
                      )}
                    </div>
                    {item.status === "success" && (
                      <button
                        onClick={() => removeItem(item.id)}
                        className="mt-0.5 text-slate-400 hover:text-slate-600"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
