import { useMutation, useQuery } from "@tanstack/react-query";
import ePub, { Book, Rendition } from "epubjs";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getBook, getBookFileUrl, getBookProgress, getToken, saveBookProgress } from "@/lib/api";

export function BookReaderPage() {
  const { bookId } = useParams();
  const numericBookId = Number(bookId);
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const bookRef = useRef<Book | null>(null);
  const renditionRef = useRef<Rendition | null>(null);
  const lastSavedCfiRef = useRef<string | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const [readerError, setReaderError] = useState<string | null>(null);

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
    if (!Number.isFinite(numericBookId) || !viewerRef.current || progressQuery.isLoading) return;

    let cancelled = false;
    const token = getToken();
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
    const epubBook = ePub(getBookFileUrl(numericBookId), { openAs: "epub", requestHeaders: headers });
    const rendition = epubBook.renderTo(viewerRef.current, {
      width: "100%",
      height: "100%",
      flow: "paginated",
      spread: "none"
    });
    bookRef.current = epubBook;
    renditionRef.current = rendition;

    rendition.on("relocated", (location: { start?: { cfi?: string } }) => {
      const cfi = location.start?.cfi;
      if (!cfi || cfi === lastSavedCfiRef.current) return;
      lastSavedCfiRef.current = cfi;
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(() => {
        saveProgressMutation.mutate(cfi);
      }, 500);
    });

    const savedCfi = progressQuery.data?.location_cfi ?? undefined;
    rendition.display(savedCfi).catch(() => {
      if (!cancelled) setReaderError("打开失败，请确认文件格式正确");
    });

    return () => {
      cancelled = true;
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
      renditionRef.current = null;
      bookRef.current = null;
      rendition.destroy();
      epubBook.destroy();
    };
  }, [numericBookId, progressQuery.data?.location_cfi, progressQuery.isLoading]);

  function goPrevious() {
    renditionRef.current?.prev();
  }

  function goNext() {
    renditionRef.current?.next();
  }

  const title = bookQuery.data?.title ?? "Reader";

  return (
    <div className="flex min-h-[calc(100vh-9rem)] flex-col gap-4">
      <div className="flex flex-col justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 md:flex-row md:items-center">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">EPUB Reader</p>
          <h1 className="mt-1 line-clamp-1 text-xl font-semibold">{title}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link to="/books">返回图书区</Link>
          </Button>
          <Button type="button" variant="outline" className="gap-2" onClick={goPrevious}>
            <ChevronLeft className="h-4 w-4" />
            上一页
          </Button>
          <Button type="button" className="gap-2" onClick={goNext}>
            下一页
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {bookQuery.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{bookQuery.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {readerError ? (
        <Alert variant="destructive">
          <AlertDescription>{readerError}</AlertDescription>
        </Alert>
      ) : null}

      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-soft">
        <div id="viewer" ref={viewerRef} className="h-[calc(100vh-15rem)] min-h-[560px] w-full" />
      </div>
    </div>
  );
}
