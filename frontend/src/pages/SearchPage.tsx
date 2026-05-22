import { useQuery } from "@tanstack/react-query";
import { FileText, Search, X } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { TagPill } from "@/components/TagSelector";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getDocuments, getTags } from "@/lib/api";
import { TagRead } from "@/lib/types";

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
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const tags = tagsQuery.data ?? [];
  const parsed = useMemo(() => parseSearch(query, tags), [query, tags]);
  const activeTag = parsed.selectedTags[0];
  const showTagSuggestions = /(^|\s)#[^\s#]*$/.test(query);
  const tagNeedle = query.match(/#([^\s#]*)$/)?.[1]?.toLowerCase() ?? "";
  const suggestedTags = tags.filter((tag) => tag.name.toLowerCase().includes(tagNeedle)).slice(0, 8);
  const enabled = Boolean(parsed.keyword || activeTag);

  const documentsQuery = useQuery({
    queryKey: ["document-search-with-tags", parsed.keyword, activeTag?.id],
    queryFn: () => getDocuments({
      page: 1,
      size: 30,
      keyword: parsed.keyword || undefined,
      tag_id: activeTag?.id,
      sort_by: "created_at",
      sort_order: "desc"
    }),
    enabled
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
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">搜索</h1>
        <p className="mt-2 text-sm text-slate-500">输入关键词检索文档；输入 # 可选择标签，支持“扩散模型 #论文 #重要”这样的组合。</p>
      </div>

      <form onSubmit={handleSearch} className="relative flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索关键词，或输入 # 选择标签"
            className="w-full rounded-full border border-slate-200 bg-white py-3 pl-10 pr-10 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
          />
          {query ? (
            <button type="button" onClick={clearSearch} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
              <X className="h-4 w-4" />
            </button>
          ) : null}
          {showTagSuggestions && suggestedTags.length > 0 ? (
            <div className="absolute left-0 right-0 top-14 z-10 rounded-2xl border border-slate-100 bg-white p-2 shadow-lg">
              {suggestedTags.map((tag) => (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => chooseTag(tag)}
                  className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-slate-50"
                >
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: tag.color ?? "#2563eb" }} />
                  #{tag.name}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <Button type="submit" disabled={!query.trim() || documentsQuery.isLoading} className="rounded-full px-5">
          <Search className="h-4 w-4" />
          搜索
        </Button>
      </form>

      {(parsed.keyword || parsed.selectedTags.length > 0) && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
          {parsed.keyword ? <span className="rounded-full bg-slate-100 px-3 py-1">关键词：{parsed.keyword}</span> : null}
          {parsed.selectedTags.map((tag) => <TagPill key={tag.id} tag={tag} />)}
          {parsed.selectedTags.length > 1 ? <span>当前后端按第一个标签过滤，其余标签用于提示。</span> : null}
        </div>
      )}

      {!enabled ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 p-12 text-center">
            <FileText className="h-12 w-12 text-slate-300" />
            <div>
              <p className="text-lg font-medium text-slate-900">从关键词或 #标签 开始</p>
              <p className="mt-1 text-sm text-slate-500">标签过滤会先缩小文档范围，再叠加关键词筛选。</p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {documentsQuery.isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, index) => <div key={index} className="h-24 animate-pulse rounded-lg bg-slate-100" />)}
        </div>
      ) : null}

      {documentsQuery.isError ? (
        <Card><CardContent className="p-6 text-sm text-red-600">{documentsQuery.error.message}</CardContent></Card>
      ) : null}

      {documentsQuery.data && documentsQuery.data.items.length === 0 ? (
        <Card><CardContent className="p-6 text-sm text-slate-500">没有找到匹配的文档。可以减少关键词，或换一个标签。</CardContent></Card>
      ) : null}

      {documentsQuery.data && documentsQuery.data.items.length > 0 ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-500">找到 {documentsQuery.data.total} 个文档结果</p>
          {documentsQuery.data.items.map((document) => (
            <button
              key={document.id}
              type="button"
              onClick={() => navigate(`/documents/${document.id}`)}
              className="w-full rounded-2xl border border-slate-100 bg-white p-4 text-left shadow-sm transition hover:border-slate-200 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="font-semibold text-slate-950">{document.title}</p>
                  <p className="mt-1 line-clamp-2 text-sm text-slate-500">{document.content_summary || document.original_filename}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {document.tags.map((tag) => <TagPill key={tag.id} tag={tag} />)}
                    {!document.tags.length ? <span className="text-xs text-slate-400">无标签</span> : null}
                  </div>
                </div>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">{document.status}</span>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
