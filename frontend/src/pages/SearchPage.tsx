import { useQuery } from "@tanstack/react-query";
import { FileText, Search, X } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { TagPill } from "@/components/TagSelector";
import { Button } from "@/components/ui/button";
import { getDocuments, getTags, searchDocumentChunks } from "@/lib/api";
import { TagRead } from "@/lib/types";
import { cn } from "@/lib/utils";

function parseSearch(raw: string, tags: TagRead[]) {
  const requestedNames = Array.from(raw.matchAll(/#([^\s#]+)/g)).map((match) => match[1].toLowerCase());
  const selectedTags = tags.filter((tag) => requestedNames.includes(tag.name.toLowerCase()));
  const keyword = raw.replace(/#[^\s#]+/g, " ").replace(/\s+/g, " ").trim();
  return { keyword, selectedTags };
}

export function SearchPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [activeTab, setActiveTab] = useState<"documents" | "chunks">("documents");
  const [fileType, setFileType] = useState("");
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const tags = tagsQuery.data ?? [];
  const parsed = useMemo(() => parseSearch(query, tags), [query, tags]);
  const activeTag = parsed.selectedTags[0];
  const showTagSuggestions = /(^|\s)#[^\s#]*$/.test(query);
  const tagNeedle = query.match(/#([^\s#]*)$/)?.[1]?.toLowerCase() ?? "";
  const suggestedTags = tags.filter((tag) => tag.name.toLowerCase().includes(tagNeedle)).slice(0, 8);
  const enabled = Boolean(parsed.keyword || activeTag);

  const documentsQuery = useQuery({
    queryKey: ["document-search-with-tags", parsed.keyword, activeTag?.id, fileType],
    queryFn: () => getDocuments({ page: 1, size: 30, keyword: parsed.keyword || undefined, tag_id: activeTag?.id, file_type: fileType as any, sort_by: "created_at", sort_order: "desc" }),
    enabled
  });
  const chunksQuery = useQuery({
    queryKey: ["chunk-search-with-tags", parsed.keyword, activeTag?.id],
    queryFn: () => searchDocumentChunks(parsed.keyword || query.replace(/#/g, " ").trim(), 20, undefined, 0),
    enabled: enabled && Boolean(parsed.keyword)
  });

  function handleSearch(event: FormEvent) {
    event.preventDefault();
    if (query.trim()) setSearchParams({ q: query.trim() });
  }

  function clearSearch() {
    setQuery("");
    setSearchParams({});
  }

  function chooseTag(tag: TagRead) {
    const next = query.replace(/#([^\s#]*)$/, "").trimEnd();
    setQuery(`${next}${next ? " " : ""}#${tag.name} `);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <section className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">搜索</h1>
        <select value={fileType} onChange={(event) => setFileType(event.target.value)} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none">
          <option value="">全部类型</option>
          <option value="pdf">PDF</option>
          <option value="markdown">Markdown</option>
          <option value="txt">TXT</option>
          <option value="image">图片</option>
          <option value="epub">EPUB</option>
          <option value="docx">DOCX</option>
        </select>
      </section>

      <form onSubmit={handleSearch} className="relative rounded-3xl border border-slate-100 bg-white p-2">
        <div className="relative flex items-center gap-2">
          <Search className="absolute left-4 h-4 w-4 text-slate-400" />
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索，或输入 #标签"
            className="h-12 flex-1 rounded-2xl border border-transparent bg-slate-50 pl-10 pr-10 text-sm outline-none transition focus:border-slate-200 focus:bg-white"
          />
          {query ? (
            <button type="button" onClick={clearSearch} className="absolute right-24 text-slate-400 hover:text-slate-600">
              <X className="h-4 w-4" />
            </button>
          ) : null}
          <Button type="submit" disabled={!query.trim() || documentsQuery.isLoading} className="h-12 rounded-2xl px-5">
            搜索
          </Button>
        </div>

        {showTagSuggestions && suggestedTags.length > 0 ? (
          <div className="absolute left-2 right-2 top-16 z-10 rounded-2xl border border-slate-100 bg-white p-2 shadow-lg">
            {suggestedTags.map((tag) => (
              <button key={tag.id} type="button" onClick={() => chooseTag(tag)} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-slate-50">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: tag.color ?? "#2563eb" }} />
                #{tag.name}
              </button>
            ))}
          </div>
        ) : null}
      </form>

      {(parsed.keyword || parsed.selectedTags.length > 0) ? (
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
          {parsed.keyword ? <span className="rounded-full bg-slate-100 px-3 py-1">{parsed.keyword}</span> : null}
          {parsed.selectedTags.slice(0, 1).map((tag) => <TagPill key={tag.id} tag={tag} />)}
        </div>
      ) : null}

      <div className="flex w-fit gap-1 rounded-2xl bg-slate-50 p-1">
        <button type="button" onClick={() => setActiveTab("documents")} className={cn("rounded-xl px-3 py-2 text-sm text-slate-500", activeTab === "documents" && "bg-white text-slate-950 shadow-sm")}>文档</button>
        <button type="button" onClick={() => setActiveTab("chunks")} className={cn("rounded-xl px-3 py-2 text-sm text-slate-500", activeTab === "chunks" && "bg-white text-slate-950 shadow-sm")}>片段</button>
      </div>

      {!enabled ? (
        <div className="flex min-h-[360px] items-center justify-center rounded-3xl border border-dashed border-slate-100 text-sm text-slate-400">
          输入关键词开始搜索
        </div>
      ) : null}

      {activeTab === "documents" && documentsQuery.isLoading ? <ResultSkeleton /> : null}
      {activeTab === "documents" && documentsQuery.isError ? <ErrorBlock message={documentsQuery.error.message} /> : null}
      {activeTab === "documents" && documentsQuery.data?.items.length === 0 ? <EmptyBlock text="无文档结果" /> : null}
      {activeTab === "documents" && documentsQuery.data && documentsQuery.data.items.length > 0 ? (
        <div className="space-y-2">
          <p className="px-1 text-sm text-slate-400">{documentsQuery.data.total} 个文档</p>
          {documentsQuery.data.items.map((document) => (
            <button key={document.id} type="button" onClick={() => navigate(`/documents/${document.id}`)} className="w-full rounded-2xl border border-slate-100 bg-white px-4 py-3 text-left transition hover:bg-slate-50">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-950">{document.title}</p>
                  <p className="mt-1 line-clamp-1 text-sm text-slate-500">{document.content_summary || document.original_filename}</p>
                  {document.tags.length ? <div className="mt-2 flex flex-wrap gap-2">{document.tags.slice(0, 4).map((tag) => <TagPill key={tag.id} tag={tag} />)}</div> : null}
                </div>
                <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">{document.source_type}</span>
              </div>
            </button>
          ))}
        </div>
      ) : null}

      {activeTab === "chunks" && !parsed.keyword && enabled ? <EmptyBlock text="输入关键词检索片段" /> : null}
      {activeTab === "chunks" && chunksQuery.isLoading ? <ResultSkeleton /> : null}
      {activeTab === "chunks" && chunksQuery.data?.items.length === 0 ? <EmptyBlock text="无片段结果" /> : null}
      {activeTab === "chunks" && chunksQuery.data && chunksQuery.data.items.length > 0 ? (
        <div className="space-y-2">
          <p className="px-1 text-sm text-slate-400">{chunksQuery.data.total} 个片段</p>
          {chunksQuery.data.items.map((hit) => (
            <button key={hit.id} type="button" onClick={() => navigate(`/documents/${hit.document_id}`)} className="w-full rounded-2xl border border-slate-100 bg-white px-4 py-3 text-left transition hover:bg-slate-50">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-950">{hit.filename || hit.document_title}</p>
                  <p className="mt-1 line-clamp-3 text-sm leading-6 text-slate-600">{hit.text}</p>
                  <p className="mt-2 text-xs text-slate-400">#{hit.chunk_index}{hit.page_start ? ` · p.${hit.page_start}` : ""}</p>
                </div>
                <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">{(hit.score * 100).toFixed(1)}%</span>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ResultSkeleton() {
  return <div className="space-y-2">{[...Array(5)].map((_, index) => <div key={index} className="h-20 animate-pulse rounded-2xl bg-slate-50" />)}</div>;
}

function EmptyBlock({ text }: { text: string }) {
  return <div className="rounded-3xl border border-slate-100 bg-white p-8 text-center text-sm text-slate-400">{text}</div>;
}

function ErrorBlock({ message }: { message: string }) {
  return <div className="rounded-3xl border border-red-100 bg-red-50 p-4 text-sm text-red-600">{message}</div>;
}
