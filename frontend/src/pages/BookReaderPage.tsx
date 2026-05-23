import { useMutation, useQuery } from "@tanstack/react-query";
import ePub, { Book, Rendition } from "epubjs";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
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

    rendition.themes.default({
      body: {
        "font-family": "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
        color: "#111827",
        "line-height": "1.9",
        "background-color": "#fbf7ef"
      },
      p: {
        "margin-block": "0.75em"
      },
      "::selection": {
        background: "rgba(15, 23, 42, 0.16)"
      }
    });

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

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goPrevious();
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        goNext();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const title = bookQuery.data?.title ?? "Reader";

  return (
    <div className="relative flex h-screen overflow-hidden bg-[#fbf7ef] text-slate-950">
      <div className="pointer-events-none fixed inset-x-0 top-0 z-10 flex items-center justify-between px-5 py-4">
        <div className="max-w-[min(44rem,calc(100vw-12rem))] truncate rounded-full bg-[#fbf7ef]/80 px-4 py-2 text-sm font-medium text-slate-600 shadow-sm backdrop-blur-md">
          {title}
        </div>
        <Button asChild variant="ghost" size="icon" className="pointer-events-auto rounded-full bg-[#fbf7ef]/80 shadow-sm backdrop-blur-md hover:bg-white/90" aria-label="退出阅读">
          <Link to="/books">
            <X className="h-4 w-4" />
          </Link>
        </Button>
      </div>

      {bookQuery.isError ? (
        <div className="fixed inset-x-4 top-20 z-20 mx-auto max-w-3xl">
          <Alert variant="destructive">
            <AlertDescription>{bookQuery.error.message}</AlertDescription>
          </Alert>
        </div>
      ) : null}
      {readerError ? (
        <div className="fixed inset-x-4 top-20 z-20 mx-auto max-w-3xl">
          <Alert variant="destructive">
            <AlertDescription>{readerError}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      <button
        type="button"
        aria-label="上一页"
        onClick={goPrevious}
        className="group absolute inset-y-0 left-0 z-[5] hidden w-24 items-center justify-start px-5 text-slate-400 transition hover:text-slate-950 md:flex"
      >
        <span className="rounded-full bg-white/0 p-3 transition group-hover:bg-white/70 group-hover:shadow-sm">
          <ChevronLeft className="h-6 w-6" />
        </span>
      </button>

      <main className="mx-auto h-full w-full max-w-5xl px-6 pb-8 pt-16 sm:px-10 md:px-16 lg:px-20">
        <div id="viewer" ref={viewerRef} className="h-full w-full" />
      </main>

      <button
        type="button"
        aria-label="下一页"
        onClick={goNext}
        className="group absolute inset-y-0 right-0 z-[5] hidden w-24 items-center justify-end px-5 text-slate-400 transition hover:text-slate-950 md:flex"
      >
        <span className="rounded-full bg-white/0 p-3 transition group-hover:bg-white/70 group-hover:shadow-sm">
          <ChevronRight className="h-6 w-6" />
        </span>
      </button>

      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-10 hidden justify-center bg-gradient-to-t from-[#fbf7ef] to-transparent px-4 pb-4 pt-12 text-xs text-slate-400 md:flex">
        ← / → 翻页
      </div>
    </div>
  );
}
