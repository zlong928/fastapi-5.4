import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";
import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { createBookmark } from "@/lib/api";

interface BookmarkSaveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function BookmarkSaveDialog({ open, onOpenChange }: BookmarkSaveDialogProps) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const bookmarkMutation = useMutation({
    mutationFn: createBookmark,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setUrl("");
      setTitle("");
      onOpenChange(false);
    }
  });

  if (!open) return null;

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmedUrl = url.trim();
    if (!trimmedUrl || bookmarkMutation.isPending) return;
    bookmarkMutation.mutate({
      url: trimmedUrl,
      title: title.trim() || undefined,
      processing_mode: "auto"
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-modal="true">
      <form onSubmit={submit} className="w-full max-w-lg rounded-3xl border border-slate-100 bg-white p-4 shadow-xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight">保存链接</h2>
          <Button type="button" variant="ghost" size="sm" className="h-8 w-8 rounded-xl p-0" onClick={() => onOpenChange(false)}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="text-sm text-slate-500">URL</span>
            <input
              value={url}
              onChange={(event) => bookmarkMutation.reset() || setUrl(event.target.value)}
              placeholder="https://..."
              className="mt-1 h-11 w-full rounded-2xl border border-slate-100 bg-slate-50 px-3 text-sm outline-none transition focus:border-slate-200 focus:bg-white"
              autoFocus
            />
          </label>
          <label className="block">
            <span className="text-sm text-slate-500">标题</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="可选"
              className="mt-1 h-10 w-full rounded-2xl border border-slate-100 bg-slate-50 px-3 text-sm outline-none transition focus:border-slate-200 focus:bg-white"
            />
          </label>
          {bookmarkMutation.isError ? <p className="text-sm text-red-600">{bookmarkMutation.error.message || "保存失败"}</p> : null}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          <Button type="submit" size="sm" className="rounded-xl" disabled={!url.trim() || bookmarkMutation.isPending}>
            {bookmarkMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存
          </Button>
        </div>
      </form>
    </div>
  );
}
