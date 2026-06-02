import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileUp, Loader2, Paperclip, UploadCloud, X } from "lucide-react";
import { ChangeEvent, ClipboardEvent, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { batchUploadDocuments, uploadDocument } from "@/lib/api";
import { DOCUMENT_PROCESSING_MODE_OPTIONS, DocumentBatchUploadItem, DocumentProcessingMode } from "@/lib/types";

export interface WorkspaceUploadPasteBatch {
  id: number;
  files: File[];
}

interface WorkspaceUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pasteBatch?: WorkspaceUploadPasteBatch | null;
}

export const ACCEPTED_KNOWLEDGE_FILES = [
  ".pdf",
  ".md",
  ".markdown",
  ".txt",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".epub",
  ".docx",
  ".mp4",
  ".mov",
  ".m4v",
  ".webm",
  ".avi",
  ".mkv",
  "video/mp4",
  "video/quicktime",
  "video/x-m4v",
  "video/webm",
  "video/x-msvideo",
  "video/x-matroska"
].join(",");

const ACCEPTED_EXTENSIONS = new Set(["pdf", "md", "markdown", "txt", "png", "jpg", "jpeg", "webp", "epub", "docx", "mp4", "mov", "m4v", "webm", "avi", "mkv"]);
const ACCEPTED_MIME_PREFIXES = ["image/", "video/"];

export function isAcceptedKnowledgeFile(file: File) {
  const extension = file.name.includes(".") ? file.name.split(".").pop()?.toLowerCase() : undefined;
  if (extension && ACCEPTED_EXTENSIONS.has(extension)) return true;
  return ACCEPTED_MIME_PREFIXES.some((prefix) => file.type.startsWith(prefix));
}

function resultStatus(item: DocumentBatchUploadItem) {
  if (!item.ok) return item.error ?? "失败";
  if (item.status === "pending") return "等待";
  if (item.status === "processing") return "解析中";
  if (item.status === "failed") return "失败";
  if (item.status === "done" || item.status === "completed") return "完成";
  return "已入队";
}

export function WorkspaceUploadDialog({ open, onOpenChange, pasteBatch }: WorkspaceUploadDialogProps) {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [processingMode, setProcessingMode] = useState<DocumentProcessingMode>("auto");
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<DocumentBatchUploadItem[]>([]);

  const selectedSummary = useMemo(() => {
    if (!files.length) return "PDF / EPUB / Markdown / TXT / Image / Video";
    if (files.length === 1) return files[0].name;
    return `${files.length} 个文件`;
  }, [files]);

  useEffect(() => {
    if (!open || !pasteBatch?.files.length) return;
    setFiles(pasteBatch.files);
    setResults([]);
    setProgress(0);
  }, [open, pasteBatch?.id]);

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (files.length === 1) {
        const response = await uploadDocument(files[0], title || undefined, processingMode, setProgress);
        return [{ filename: files[0].name, ok: true, document_id: response.document_id, parse_job_id: response.parse_job_id, status: response.status, processing_mode: response.processing_mode }] as DocumentBatchUploadItem[];
      }
      return batchUploadDocuments(files, processingMode);
    },
    onSuccess: (items) => {
      setResults(items);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["statistics"] });
      queryClient.invalidateQueries({ queryKey: ["collections"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  function onFilesChanged(event: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(event.target.files ?? []));
    setResults([]);
    setProgress(0);
  }

  function onPasteFiles(event: ClipboardEvent<HTMLElement>) {
    const pastedFiles = Array.from(event.clipboardData.files).filter(isAcceptedKnowledgeFile);
    if (!pastedFiles.length) return;
    event.preventDefault();
    setFiles(pastedFiles);
    setResults([]);
    setProgress(0);
  }

  function closeDialog() {
    onOpenChange(false);
    setFiles([]);
    setTitle("");
    setProcessingMode("auto");
    setProgress(0);
    setResults([]);
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/20 px-4 backdrop-blur-sm">
      <div className="w-full max-w-xl rounded-3xl border border-slate-100 bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold tracking-tight">上传</h2>
            <p className="mt-1 text-xs text-slate-400">{selectedSummary}</p>
          </div>
          <Button type="button" variant="ghost" size="icon" className="rounded-xl" onClick={closeDialog}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-4 space-y-3">
          <label className="flex cursor-pointer items-center gap-3 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-4 transition hover:bg-slate-100" onPaste={onPasteFiles} tabIndex={0}>
            <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white text-slate-500 ring-1 ring-slate-100">
              <Paperclip className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-900">选择或粘贴文件</p>
              <p className="mt-0.5 truncate text-xs text-slate-400">{selectedSummary}</p>
            </div>
            <UploadCloud className="h-4 w-4 text-slate-400" />
            <input type="file" multiple accept={ACCEPTED_KNOWLEDGE_FILES} className="sr-only" onChange={onFilesChanged} />
          </label>

          <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_180px]">
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              disabled={files.length !== 1}
              placeholder="标题（可选）"
              className="h-10 rounded-2xl border border-slate-100 bg-white px-3 text-sm outline-none transition focus:border-slate-200 disabled:bg-slate-50 disabled:text-slate-400"
            />

            <select
              value={processingMode}
              onChange={(event) => setProcessingMode(event.target.value as DocumentProcessingMode)}
              className="h-10 rounded-2xl border border-slate-100 bg-white px-3 text-sm outline-none transition focus:border-slate-200"
            >
              {DOCUMENT_PROCESSING_MODE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          {uploadMutation.isPending && files.length === 1 ? (
            <div className="rounded-2xl bg-slate-50 p-3">
              <div className="mb-2 flex justify-between text-xs text-slate-400"><span>上传</span><span>{progress}%</span></div>
              <div className="h-1.5 rounded-full bg-slate-200"><div className="h-1.5 rounded-full bg-slate-950" style={{ width: `${progress}%` }} /></div>
            </div>
          ) : null}

          {uploadMutation.isError ? (
            <div className="flex gap-2 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-600">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{uploadMutation.error instanceof Error ? uploadMutation.error.message : "上传失败"}</span>
            </div>
          ) : null}

          {results.length ? (
            <div className="max-h-48 space-y-1 overflow-auto rounded-2xl border border-slate-100 p-2">
              {results.map((item) => (
                <div key={`${item.filename}-${item.document_id ?? item.error}`} className="flex items-center justify-between gap-3 rounded-xl px-2 py-2 text-sm hover:bg-slate-50">
                  <span className="truncate text-slate-700">{item.filename}</span>
                  <span className={item.ok ? "inline-flex items-center gap-1 text-emerald-600" : "inline-flex items-center gap-1 text-red-600"}>
                    {item.ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                    {resultStatus(item)}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="outline" className="rounded-xl border-slate-100 shadow-none" onClick={closeDialog}>关闭</Button>
          <Button
            type="button"
            className="rounded-xl bg-slate-950 text-white hover:bg-slate-800"
            disabled={!files.length || uploadMutation.isPending}
            onClick={() => uploadMutation.mutate()}
          >
            {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
            上传
          </Button>
        </div>
      </div>
    </div>
  );
}
