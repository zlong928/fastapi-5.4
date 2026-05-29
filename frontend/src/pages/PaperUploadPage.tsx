import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText, Loader2, UploadCloud } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getToken, uploadDocument } from "@/lib/api";

const MAX_PDF_SIZE_BYTES = 100 * 1024 * 1024;

function fileSizeLabel(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function PaperUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const selectedFile = useMemo(() => {
    if (!file) return null;
    return { name: file.name, size: fileSizeLabel(file.size) };
  }, [file]);

  const uploadMutation = useMutation({
    mutationFn: (target: File) => uploadDocument(target, title.trim() || undefined, "auto", setProgress),
    onMutate: () => {
      setError("");
      setProgress(2);
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["papers"] });
      navigate(`/papers/${response.document_id}`);
    },
    onError: (err) => {
      setProgress(0);
      setError(err instanceof Error ? err.message : "上传失败");
    }
  });

  function submit() {
    setError("");
    if (!file) {
      setError("请选择 PDF 文件");
      return;
    }
    if (!getToken()) {
      setError("请先登录后再上传论文。");
      return;
    }
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("仅支持 PDF 文件");
      return;
    }
    if (file.size > MAX_PDF_SIZE_BYTES) {
      setError(`文件过大，当前前端限制为 ${fileSizeLabel(MAX_PDF_SIZE_BYTES)}。`);
      return;
    }
    uploadMutation.mutate(file);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm" className="rounded-xl px-2 text-slate-500">
          <Link to="/papers"><ArrowLeft className="h-4 w-4" />论文列表</Link>
        </Button>
      </div>

      <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-500">论文上传</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">上传 PDF 并进入解析流程</h1>
          </div>
          <FileText className="h-5 w-5 text-slate-400" />
        </div>

        {error ? (
          <Alert variant="destructive" className="mt-4 rounded-xl">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_280px]">
          <label className="flex min-h-56 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-5 py-8 text-center transition hover:border-slate-300 hover:bg-white">
            <input type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-slate-700 ring-1 ring-slate-200">
              <UploadCloud className="h-5 w-5" />
            </span>
            <span className="mt-4 text-base font-medium text-slate-900">{selectedFile?.name ?? "选择 PDF 文件"}</span>
            <span className="mt-1 text-sm text-slate-500">{selectedFile?.size ?? "PDF"}</span>
          </label>

          <div className="space-y-4 rounded-2xl border border-slate-100 p-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">标题</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={file?.name.replace(/\.pdf$/i, "") ?? "默认使用文件名"}
                className="mt-2 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none transition focus:ring-2 focus:ring-slate-200"
              />
            </label>

            <div className="space-y-2">
              <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-slate-900 transition-all" style={{ width: `${progress}%` }} />
              </div>
              <p className="text-xs text-slate-500">{uploadMutation.isPending ? `上传中 ${progress}%` : "等待上传"}</p>
            </div>

            <Button type="button" className="w-full rounded-xl" onClick={submit} disabled={uploadMutation.isPending}>
              {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
              上传论文
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
