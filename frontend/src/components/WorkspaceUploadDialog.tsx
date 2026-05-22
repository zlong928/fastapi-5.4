import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileUp, Loader2, UploadCloud, X } from "lucide-react";
import { ChangeEvent, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { batchUploadDocuments, uploadDocument } from "@/lib/api";
import { DOCUMENT_PROCESSING_MODE_OPTIONS, DocumentBatchUploadItem, DocumentProcessingMode } from "@/lib/types";

interface WorkspaceUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function WorkspaceUploadDialog({ open, onOpenChange }: WorkspaceUploadDialogProps) {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [processingMode, setProcessingMode] = useState<DocumentProcessingMode>("auto");
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<DocumentBatchUploadItem[]>([]);

  const selectedSummary = useMemo(() => {
    if (!files.length) return "未选择文件";
    if (files.length === 1) return files[0].name;
    return `${files.length} 个文件已选择`;
  }, [files]);

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
    }
  });

  function onFilesChanged(event: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(event.target.files ?? []));
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
      <div className="w-full max-w-2xl rounded-3xl border border-slate-200 bg-white p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">上传知识文档</h2>
            <p className="mt-1 text-sm text-slate-500">支持单文件和批量上传，上传后会自动进入解析队列。</p>
          </div>
          <Button type="button" variant="ghost" size="icon" className="rounded-full" onClick={closeDialog}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="space-y-4 py-5">
          <label className="flex cursor-pointer flex-col items-center justify-center rounded-3xl border border-dashed border-slate-300 bg-slate-50/70 px-6 py-8 text-center transition hover:bg-slate-100">
            <UploadCloud className="h-10 w-10 text-slate-400" />
            <span className="mt-3 text-sm font-medium text-slate-800">点击选择文件</span>
            <span className="mt-1 text-xs text-slate-500">PDF、Markdown、TXT、图片等知识资料</span>
            <input type="file" multiple className="sr-only" onChange={onFilesChanged} />
          </label>

          <div className="rounded-2xl border border-slate-100 bg-white px-4 py-3 text-sm text-slate-600">
            {selectedSummary}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label>
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">标题</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                disabled={files.length !== 1}
                placeholder={files.length === 1 ? "可选，默认使用文件名" : "批量上传不设置统一标题"}
                className="mt-1 h-10 w-full rounded-2xl border border-slate-200 px-3 text-sm outline-none transition focus:border-slate-400 disabled:bg-slate-50 disabled:text-slate-400"
              />
            </label>
            <label>
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">处理模式</span>
              <select
                value={processingMode}
                onChange={(event) => setProcessingMode(event.target.value as DocumentProcessingMode)}
                className="mt-1 h-10 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm outline-none transition focus:border-slate-400"
              >
                {DOCUMENT_PROCESSING_MODE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>

          {uploadMutation.isPending && files.length === 1 ? (
            <div className="rounded-2xl bg-slate-50 p-3">
              <div className="mb-2 flex justify-between text-xs text-slate-500"><span>上传进度</span><span>{progress}%</span></div>
              <div className="h-2 rounded-full bg-slate-200"><div className="h-2 rounded-full bg-slate-950" style={{ width: `${progress}%` }} /></div>
            </div>
          ) : null}

          {uploadMutation.isError ? (
            <div className="flex gap-2 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{uploadMutation.error instanceof Error ? uploadMutation.error.message : "上传失败"}</span>
            </div>
          ) : null}

          {results.length ? (
            <div className="max-h-48 space-y-2 overflow-auto rounded-2xl border border-slate-100 p-3">
              {results.map((item) => (
                <div key={`${item.filename}-${item.document_id ?? item.error}`} className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate text-slate-700">{item.filename}</span>
                  <span className={item.ok ? "inline-flex items-center gap-1 text-emerald-600" : "inline-flex items-center gap-1 text-red-600"}>
                    {item.ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                    {item.ok ? "已入队" : item.error ?? "失败"}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
          <Button type="button" variant="outline" className="rounded-full" onClick={closeDialog}>关闭</Button>
          <Button
            type="button"
            className="rounded-full bg-slate-950 text-white hover:bg-slate-800"
            disabled={!files.length || uploadMutation.isPending}
            onClick={() => uploadMutation.mutate()}
          >
            {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
            开始上传
          </Button>
        </div>
      </div>
    </div>
  );
}
