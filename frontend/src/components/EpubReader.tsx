import ePub, { Book, Rendition } from "epubjs";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getToken } from "@/lib/api";

type EpubReaderProps = {
  title: string;
  fileUrl: string;
  progressKey: string;
  heightClassName?: string;
  compact?: boolean;
};

export function EpubReader({ title, fileUrl, progressKey, heightClassName = "h-[72vh] min-h-[620px]", compact = false }: EpubReaderProps) {
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const bookRef = useRef<Book | null>(null);
  const renditionRef = useRef<Rendition | null>(null);
  const lastSavedCfiRef = useRef<string | null>(null);
  const [readerError, setReaderError] = useState<string | null>(null);

  useEffect(() => {
    if (!viewerRef.current || !fileUrl) return;

    let cancelled = false;
    setReaderError(null);
    const token = getToken();
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
    const epubBook = ePub(fileUrl, { openAs: "epub", requestHeaders: headers });
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
      localStorage.setItem(progressKey, cfi);
    });

    const savedCfi = localStorage.getItem(progressKey) ?? undefined;
    rendition.display(savedCfi).catch(() => {
      if (!cancelled) setReaderError("打开失败，请确认 EPUB 文件格式正确。");
    });

    return () => {
      cancelled = true;
      renditionRef.current = null;
      bookRef.current = null;
      rendition.destroy();
      epubBook.destroy();
    };
  }, [fileUrl, progressKey]);

  function goPrevious() { renditionRef.current?.prev(); }
  function goNext() { renditionRef.current?.next(); }

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        {compact ? <span className="text-sm font-medium text-slate-500">EPUB 阅读</span> : <div className="min-w-0"><p className="text-xs font-medium uppercase tracking-wide text-slate-500">EPUB Reader</p><p className="truncate text-sm font-semibold text-slate-900">{title}</p></div>}
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" className="gap-2" onClick={goPrevious}><ChevronLeft className="h-4 w-4" />上一页</Button>
          <Button type="button" size="sm" className="gap-2" onClick={goNext}>下一页<ChevronRight className="h-4 w-4" /></Button>
        </div>
      </div>
      {readerError ? <Alert variant="destructive" className="mx-4"><AlertDescription>{readerError}</AlertDescription></Alert> : null}
      <div className="min-h-0 flex-1 overflow-hidden bg-white"><div ref={viewerRef} className={`w-full ${heightClassName}`} /></div>
    </div>
  );
}