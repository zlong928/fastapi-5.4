import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { EpubReader } from "@/components/EpubReader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getBook, getBookFileUrl, getBookProgress, saveBookProgress } from "@/lib/api";

export function BookReaderPage() {
  const { bookId } = useParams();
  const numericBookId = Number(bookId);
  const storageKey = `book-progress-${numericBookId}`;
  const previousCfiRef = useRef<string | null>(null);

  const bookQuery = useQuery({
    queryKey: ["books", numericBookId],
    queryFn: () => getBook(numericBookId),
    enabled: Number.isFinite(numericBookId)
  });
  const progressQuery = useQuery({
    queryKey: ["books", numericBookId, "progress"],
    queryFn: () => getBookProgress(numericBookId),
    enabled: Number.isFinite(numericBookId)
  });
  const saveProgressMutation = useMutation({
    mutationFn: (locationCfi: string) => saveBookProgress(numericBookId, { location_cfi: locationCfi, progress_percent: null })
  });

  useEffect(() => {
    if (progressQuery.data?.location_cfi) {
      localStorage.setItem(storageKey, progressQuery.data.location_cfi);
    }
  }, [progressQuery.data?.location_cfi, storageKey]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const cfi = localStorage.getItem(storageKey);
      if (!cfi || cfi === previousCfiRef.current) return;
      previousCfiRef.current = cfi;
      saveProgressMutation.mutate(cfi);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [storageKey]);

  const title = bookQuery.data?.title ?? "Reader";

  return (
    <div className="flex min-h-[calc(100vh-9rem)] flex-col gap-4">
      <div className="flex flex-col justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 md:flex-row md:items-center">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">EPUB Reader</p>
          <h1 className="mt-1 line-clamp-1 text-xl font-semibold">{title}</h1>
        </div>
        <Button asChild variant="outline">
          <Link to="/knowledge">返回知识库</Link>
        </Button>
      </div>

      {bookQuery.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{bookQuery.error.message}</AlertDescription>
        </Alert>
      ) : null}

      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-soft">
        <EpubReader title={title} fileUrl={getBookFileUrl(numericBookId)} progressKey={storageKey} heightClassName="h-[calc(100vh-15rem)] min-h-[560px]" />
      </div>
    </div>
  );
}
