import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileUp, Loader2 } from "lucide-react";
import { DragEvent, useRef, useState } from "react";
import { TaskCard } from "@/components/TaskCard";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { uploadFile } from "@/lib/api";
import { TaskRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

type UploadItem = {
  name: string;
  status: "uploading" | "success" | "failed";
  task?: TaskRecord;
  error?: string;
};

function fallbackTaskFromUpload(response: Awaited<ReturnType<typeof uploadFile>>, file: File): TaskRecord {
  return {
    task_id: response.task_id,
    task_kind: "basic_file_processing",
    document_id: null,
    file_name: response.file_name ?? response.filename ?? file.name,
    file_size: file.size,
    file_type: file.name.split(".").pop()?.toLowerCase() ?? "pdf",
    status: response.status ?? "queued",
    progress: response.status === "success" || response.status === "failed" ? 100 : 0,
    error: null,
    storage_path: null,
    result_path: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
    metadata_json: null
  };
}

export function FileUploader() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [isDragging, setIsDragging] = useState(false);
  const [items, setItems] = useState<UploadItem[]>([]);

  const mutation = useMutation({
    mutationFn: async (files: File[]) => {
      const uploaded: UploadItem[] = [];
      for (const file of files) {
        setItems((current) => [...current, { name: file.name, status: "uploading" }]);
        try {
          const response = await uploadFile(file);
          const task = response.tasks?.[0] ?? fallbackTaskFromUpload(response, file);
          uploaded.push({ name: file.name, status: "success", task });
          setItems((current) => current.map((item) => (item.name === file.name && item.status === "uploading" ? { name: file.name, status: "success", task } : item)));
        } catch (error) {
          const message = error instanceof Error ? error.message : "Upload failed";
          uploaded.push({ name: file.name, status: "failed", error: message });
          setItems((current) => current.map((item) => (item.name === file.name && item.status === "uploading" ? { name: file.name, status: "failed", error: message } : item)));
        }
      }
      return uploaded;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  function uploadFiles(fileList: FileList | File[]) {
    const files = Array.from(fileList).filter((file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
    if (!files.length) {
      setItems([{ name: "No PDF selected", status: "failed", error: "Please choose one or more PDF files." }]);
      return;
    }
    mutation.mutate(files);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    uploadFiles(event.dataTransfer.files);
  }

  return (
    <div className="space-y-6">
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
        <input ref={inputRef} type="file" accept="application/pdf,.pdf" multiple className="hidden" onChange={(event) => event.target.files && uploadFiles(event.target.files)} />
        <FileUp className="mx-auto h-10 w-10 text-slate-500" />
        <h2 className="mt-4 text-lg font-semibold">Drop PDF files here</h2>
        <p className="mt-2 text-sm text-slate-500">Multiple files are uploaded one request at a time.</p>
        <Button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="mt-6"
        >
          Select PDFs
        </Button>
      </div>

      {items.length ? (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Upload results</h3>
          {items.map((item, index) => (
            <div key={`${item.name}-${index}`}>
              {item.task ? (
                <TaskCard task={item.task} />
              ) : item.status === "failed" ? (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    <span className="font-medium">{item.name}</span>
                    <span className="block">{item.error ?? "Upload failed"}</span>
                  </AlertDescription>
                </Alert>
              ) : (
                <Card>
                  <CardContent className="flex items-start gap-3 p-4">
                  {item.status === "uploading" ? <Loader2 className="mt-0.5 h-5 w-5 animate-spin text-blue-600" /> : null}
                  {item.status === "success" ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" /> : null}
                  <div>
                    <p className="font-medium">{item.name}</p>
                    <p className="text-sm text-slate-500">{item.error ?? item.status}</p>
                  </div>
                  </CardContent>
                </Card>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
