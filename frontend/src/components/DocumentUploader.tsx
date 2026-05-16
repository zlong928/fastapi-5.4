import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileUp, Loader2, X } from "lucide-react";
import { DragEvent, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { uploadDocument } from "@/lib/api";
import { DOCUMENT_PROCESSING_MODE_OPTIONS, DocumentProcessingMode, DocumentUploadResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

type UploadItem = {
  id: string;
  name: string;
  title?: string;
  status: "uploading" | "success" | "failed";
  document?: DocumentUploadResponse;
  error?: string;
};

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
        setItems((current) => [...current, { id, name: file.name, status: "uploading" }]);
        try {
          const document = await uploadDocument(file, customTitle || undefined, processingMode);
          uploaded.push({ id, name: file.name, status: "success", document });
          setItems((current) =>
            current.map((item) =>
              item.id === id ? { id, name: file.name, status: "success", document } : item
            )
          );
        } catch (error) {
          const message = error instanceof Error ? error.message : "Upload failed";
          uploaded.push({ id, name: file.name, status: "failed", error: message });
          setItems((current) =>
            current.map((item) =>
              item.id === id ? { id, name: file.name, status: "failed", error: message } : item
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
    const supportedTypes = ["application/pdf", "text/markdown", "text/plain", "image/png", "image/jpeg", "image/webp"];
    const files = Array.from(fileList).filter((file) => {
      const isSupportedType = supportedTypes.includes(file.type);
      const isSupportedExt =
        file.name.toLowerCase().endsWith(".pdf") ||
        file.name.toLowerCase().endsWith(".md") ||
        file.name.toLowerCase().endsWith(".txt") ||
        file.name.toLowerCase().endsWith(".png") ||
        file.name.toLowerCase().endsWith(".jpg") ||
        file.name.toLowerCase().endsWith(".jpeg") ||
        file.name.toLowerCase().endsWith(".webp");
      return isSupportedType || isSupportedExt;
    });

    if (!files.length) {
      setItems([
        {
          id: `error-${Date.now()}`,
          name: "No supported files selected",
          status: "failed",
          error: "Please choose PDF, Markdown (.md), text (.txt), or image files."
        }
      ]);
      return;
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
      {/* Custom Title Input */}
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

      {/* Drop Zone */}
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
          accept=".pdf,.md,.txt,.png,.jpg,.jpeg,.webp,application/pdf,text/markdown,text/plain,image/png,image/jpeg,image/webp"
          multiple
          disabled={mutation.isPending}
          className="hidden"
          onChange={(event) => event.target.files && uploadFiles(event.target.files)}
        />
        <FileUp className="mx-auto h-10 w-10 text-slate-500" />
        <h2 className="mt-4 text-lg font-semibold">Drop files here</h2>
        <p className="mt-2 text-sm text-slate-500">
          Supports PDF, Markdown (.md), text (.txt), and images
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

      {/* Upload Results */}
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
                          Status: <span className="capitalize">{item.document.status}</span>
                          <span className="ml-2">Mode: {selectedMode?.label}</span>
                        </p>
                      )}
                      {item.status === "uploading" && (
                        <p className="text-sm text-slate-500">Uploading...</p>
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
