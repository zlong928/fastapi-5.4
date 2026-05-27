import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, UploadCloud } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getPapers, uploadPaper } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { DocumentStatus } from "@/lib/types";

function statusText(status: DocumentStatus | string) {
  const labels: Record<string, string> = { uploaded: "已上传", parsing: "解析中", parsed: "已解析", extracting: "提取中", done: "已完成", failed: "失败" };
  return labels[status] ?? status;
}

export function PapersPage() {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const papersQuery = useQuery({ queryKey: ["papers"], queryFn: getPapers });
  const uploadMutation = useMutation({
    mutationFn: (target: File) => uploadPaper(target),
    onSuccess: (paper) => {
      queryClient.invalidateQueries({ queryKey: ["papers"] });
      navigate(`/papers/${paper.id}`);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "上传失败")
  });

  function submit() {
    setError("");
    if (!file) {
      setError("请选择 PDF 文件");
      return;
    }
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("仅支持 PDF 文件");
      return;
    }
    uploadMutation.mutate(file);
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <section className="rounded-3xl border border-slate-100 bg-white p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-950">论文上传</h1>
            <p className="mt-1 text-sm text-slate-400">仅支持 PDF 文件</p>
          </div>
          <FileText className="h-5 w-5 text-slate-400" />
        </div>
        {error ? <Alert variant="destructive" className="mb-3 rounded-2xl"><AlertDescription>{error}</AlertDescription></Alert> : null}
        <div className="flex flex-col gap-3 sm:flex-row">
          <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="min-h-10 flex-1 rounded-2xl border border-slate-100 px-3 py-2 text-sm" />
          <Button type="button" className="rounded-xl" onClick={submit} disabled={uploadMutation.isPending}>
            {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
            上传论文
          </Button>
        </div>
      </section>

      <section className="rounded-3xl border border-slate-100 bg-white p-5">
        <h2 className="mb-3 text-base font-medium text-slate-800">论文列表</h2>
        <div className="overflow-hidden rounded-2xl border border-slate-100">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-400">
              <tr><th className="px-4 py-3">标题</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">创建时间</th><th className="px-4 py-3">操作</th></tr>
            </thead>
            <tbody>
              {(papersQuery.data ?? []).map((paper) => (
                <tr key={paper.id} className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium text-slate-800">{paper.title}</td>
                  <td className="px-4 py-3 text-slate-500">{statusText(paper.status)}</td>
                  <td className="px-4 py-3 text-slate-500">{formatChinaDateTime(paper.created_at)}</td>
                  <td className="px-4 py-3"><Button asChild size="sm" variant="outline" className="rounded-xl border-slate-100 shadow-none"><Link to={`/papers/${paper.id}`}>查看详情</Link></Button></td>
                </tr>
              ))}
              {!papersQuery.isLoading && !(papersQuery.data ?? []).length ? <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-400">暂无论文</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
