import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Library, Link2, Plus, Search, UploadCloud, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BookmarkSaveDialog } from "@/components/BookmarkSaveDialog";
import { DocumentCard } from "@/components/DocumentCard";
import { TagPill } from "@/components/TagSelector";
import { WorkspaceUploadDialog } from "@/components/WorkspaceUploadDialog";
import { Button } from "@/components/ui/button";
import { createCollection, getCollections, getDocuments, getStatistics, getTags } from "@/lib/api";
import { CollectionCreate, DocumentListParams, DocumentStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type KnowledgeTab = "documents" | "collections" | "tags";

const PAGE_SIZE = 12;
const tabs: Array<{ key: KnowledgeTab; label: string }> = [
  { key: "documents", label: "文档" },
  { key: "collections", label: "集合" },
  { key: "tags", label: "标签" }
];
const fileTypes = ["", "pdf", "markdown", "txt", "image", "epub", "docx", "bookmark"];
const fileTypeLabels: Record<string, string> = {
  pdf: "PDF",
  markdown: "Markdown",
  txt: "TXT",
  image: "图片",
  epub: "EPUB",
  docx: "DOCX",
  bookmark: "链接"
};

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") as KnowledgeTab | null;
  const [activeTab, setActiveTab] = useState<KnowledgeTab>(requestedTab && tabs.some((tab) => tab.key === requestedTab) ? requestedTab : "documents");
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(searchParams.get("upload") === "1");
  const [bookmarkOpen, setBookmarkOpen] = useState(false);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [collectionForm, setCollectionForm] = useState<CollectionCreate>({ name: "", description: "" });
  const [tagId, setTagId] = useState("");
  const [fileType, setFileType] = useState(searchParams.get("type") ?? "");
  const [status, setStatus] = useState<DocumentStatus | "">("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (searchParams.get("upload") === "1") setUploadOpen(true);
    const nextTab = searchParams.get("tab") as KnowledgeTab | null;
    if (nextTab && tabs.some((tab) => tab.key === nextTab)) setActiveTab(nextTab);
    if (searchParams.get("type")) setFileType(searchParams.get("type") ?? "");
  }, [searchParams]);

  const documentParams: DocumentListParams = useMemo(() => ({
    page,
    size: PAGE_SIZE,
    keyword: query || undefined,
    tag_id: tagId ? Number(tagId) : undefined,
    file_type: fileType as DocumentListParams["file_type"],
    status: status || undefined,
    sort_by: "created_at",
    sort_order: "desc"
  }), [fileType, page, query, status, tagId]);

  const documentsQuery = useQuery({ queryKey: ["documents", "knowledge", documentParams], queryFn: () => getDocuments(documentParams) });
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const collectionsQuery = useQuery({ queryKey: ["collections"], queryFn: getCollections });
  const statsQuery = useQuery({ queryKey: ["statistics"], queryFn: getStatistics });
  const createCollectionMutation = useMutation({
    mutationFn: createCollection,
    onSuccess: () => {
      setCollectionOpen(false);
      setCollectionForm({ name: "", description: "" });
      queryClient.invalidateQueries({ queryKey: ["collections"] });
    }
  });

  const documents = documentsQuery.data?.items ?? [];
  const tags = tagsQuery.data ?? [];
  const collections = collectionsQuery.data ?? [];
  const total = documentsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasFilters = Boolean(query || tagId || fileType || status);
  const documentsErrorMessage = documentsQuery.error instanceof Error ? documentsQuery.error.message : "加载失败";

  function chooseTab(tab: KnowledgeTab) {
    setActiveTab(tab);
    setSearchParams(tab === "documents" ? {} : { tab });
  }

  function clearFilters() {
    setQuery("");
    setTagId("");
    setFileType("");
    setStatus("");
    setPage(1);
  }

  function submitCollection(event: FormEvent) {
    event.preventDefault();
    if (!collectionForm.name.trim()) return;
    createCollectionMutation.mutate({ name: collectionForm.name.trim(), description: collectionForm.description?.trim() || undefined });
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <section className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">知识库</h1>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-sm font-medium text-slate-500">{statsQuery.data?.total_documents ?? total}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={() => setCollectionOpen(true)}>
            <Plus className="h-4 w-4" />
            新建集合
          </Button>
          <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={() => setBookmarkOpen(true)}>
            <Link2 className="h-4 w-4" />
            保存链接
          </Button>
          <Button type="button" size="sm" className="rounded-xl bg-slate-950 text-white hover:bg-slate-800" onClick={() => setUploadOpen(true)}>
            <UploadCloud className="h-4 w-4" />
            上传
          </Button>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-4">
          <div className="rounded-3xl border border-slate-100 bg-white p-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
              <label className="relative block flex-1">
                <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={query}
                  onChange={(event) => { setQuery(event.target.value); setPage(1); }}
                  placeholder="搜索资料"
                  className="h-11 w-full rounded-2xl border border-transparent bg-slate-50 pl-11 pr-4 text-sm outline-none transition focus:border-slate-200 focus:bg-white"
                />
              </label>

              <div className="flex shrink-0 gap-1 rounded-2xl bg-slate-50 p-1">
                {tabs.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => chooseTab(item.key)}
                    className={cn("rounded-xl px-3 py-2 text-sm font-medium text-slate-500 transition hover:text-slate-950", activeTab === item.key && "bg-white text-slate-950 ring-1 ring-slate-100")}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            {activeTab === "documents" ? (
              <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
                <select value={tagId} onChange={(event) => { setTagId(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none">
                  <option value="">全部标签</option>
                  {tags.map((tag) => <option key={tag.id} value={tag.id}>#{tag.name}</option>)}
                </select>
                <select value={fileType} onChange={(event) => { setFileType(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none">
                  {fileTypes.map((type) => <option key={type || "all"} value={type}>{type ? fileTypeLabels[type] ?? type.toUpperCase() : "全部类型"}</option>)}
                </select>
                <select value={status} onChange={(event) => { setStatus(event.target.value as DocumentStatus | ""); setPage(1); }} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none">
                  <option value="">全部状态</option>
                  <option value="pending">等待</option>
                  <option value="processing">解析中</option>
                  <option value="done">完成</option>
                  <option value="failed">失败</option>
                </select>
                {hasFilters ? <Button type="button" variant="ghost" size="sm" className="h-9 rounded-xl text-slate-500" onClick={clearFilters}>清空</Button> : null}
              </div>
            ) : null}
          </div>

          {activeTab === "documents" ? (
            <section className="rounded-3xl border border-slate-100 bg-white p-3">
              <div className="mb-2 flex items-center justify-between px-1 text-sm text-slate-500">
                <span className="flex items-center gap-2 font-medium text-slate-700"><Library className="h-4 w-4" />资料 · {total}</span>
                <span>{page} / {totalPages}</span>
              </div>

              {documentsQuery.isLoading ? (
                <div className="space-y-2">{[...Array(7)].map((_, index) => <div key={index} className="h-20 animate-pulse rounded-2xl bg-slate-50" />)}</div>
              ) : documentsQuery.isError ? (
                <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-red-100 bg-red-50 px-4 text-center text-sm text-red-600">加载失败：{documentsErrorMessage}</div>
              ) : documents.length ? (
                <>
                  <div className="space-y-2">{documents.map((document) => <DocumentCard key={document.id} document={document} />)}</div>
                  <div className="mt-4 flex justify-end gap-2">
                    <Button variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>上一页</Button>
                    <Button variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>下一页</Button>
                  </div>
                </>
              ) : (
                <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-slate-50 text-sm text-slate-400">无文档</div>
              )}
            </section>
          ) : null}

          {activeTab === "collections" ? (
            <section className="rounded-3xl border border-slate-100 bg-white p-4">
              <div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold text-slate-700">集合</h2><Button size="sm" className="rounded-xl" onClick={() => setCollectionOpen(true)}>新建集合</Button></div>
              {collections.length ? (
                <div className="grid gap-2 md:grid-cols-2">
                  {collections.map((collection) => <div key={collection.id} className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4"><div className="flex items-center gap-2"><FolderOpen className="h-4 w-4 text-slate-400" /><p className="font-medium text-slate-800">{collection.name}</p></div><p className="mt-2 line-clamp-2 text-sm text-slate-500">{collection.description || "暂无描述"}</p></div>)}
                </div>
              ) : <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-slate-50 text-sm text-slate-400">无集合</div>}
            </section>
          ) : null}

          {activeTab === "tags" ? (
            <section className="rounded-3xl border border-slate-100 bg-white p-4">
              <h2 className="mb-3 text-sm font-semibold text-slate-700">标签</h2>
              {tags.length ? <div className="flex flex-wrap gap-2">{tags.map((tag) => <TagPill key={tag.id} tag={tag} />)}</div> : <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-slate-50 text-sm text-slate-400">无标签</div>}
            </section>
          ) : null}
        </div>

        <aside className="hidden space-y-3 xl:block">
          <div className="rounded-3xl border border-slate-100 bg-white p-4">
            <p className="text-sm font-semibold text-slate-800">概览</p>
            <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">资料</p><p className="mt-1 text-xl font-semibold">{statsQuery.data?.total_documents ?? total}</p></div>
              <div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">失败</p><p className="mt-1 text-xl font-semibold text-red-500">{statsQuery.data?.failed_documents ?? 0}</p></div>
              <div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">集合</p><p className="mt-1 text-xl font-semibold">{collections.length}</p></div>
              <div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">标签</p><p className="mt-1 text-xl font-semibold">{tags.length}</p></div>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-100 bg-white p-4">
            <p className="text-sm font-semibold text-slate-800">常用标签</p>
            <div className="mt-3 flex flex-wrap gap-2">{tags.slice(0, 12).map((tag) => <TagPill key={tag.id} tag={tag} />)}{!tags.length ? <p className="text-sm text-slate-500">无标签</p> : null}</div>
          </div>
        </aside>
      </section>

      <WorkspaceUploadDialog open={uploadOpen} onOpenChange={(open) => { setUploadOpen(open); if (!open && searchParams.get("upload")) setSearchParams({}); }} />
      <BookmarkSaveDialog open={bookmarkOpen} onOpenChange={setBookmarkOpen} />

      {collectionOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-modal="true">
          <form onSubmit={submitCollection} className="w-full max-w-lg rounded-3xl bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div><h2 className="text-lg font-semibold tracking-tight">新建集合</h2></div>
              <Button type="button" variant="ghost" size="sm" className="rounded-xl" onClick={() => setCollectionOpen(false)}><X className="h-4 w-4" /></Button>
            </div>
            <div className="mt-5 space-y-3">
              <label className="block"><span className="text-sm font-medium text-slate-700">名称</span><input value={collectionForm.name} onChange={(event) => setCollectionForm((current) => ({ ...current, name: event.target.value }))} className="mt-1 h-10 w-full rounded-xl border border-slate-100 px-3 text-sm outline-none focus:border-slate-300" placeholder="集合名称" /></label>
              <label className="block"><span className="text-sm font-medium text-slate-700">描述</span><textarea value={collectionForm.description ?? ""} onChange={(event) => setCollectionForm((current) => ({ ...current, description: event.target.value }))} className="mt-1 min-h-24 w-full rounded-xl border border-slate-100 px-3 py-2 text-sm outline-none focus:border-slate-300" placeholder="可选" /></label>
              {createCollectionMutation.isError ? <p className="text-sm text-red-600">{createCollectionMutation.error.message}</p> : null}
            </div>
            <div className="mt-5 flex justify-end gap-2"><Button type="button" variant="outline" className="rounded-xl border-slate-100 shadow-none" onClick={() => setCollectionOpen(false)}>取消</Button><Button type="submit" className="rounded-xl" disabled={!collectionForm.name.trim() || createCollectionMutation.isPending}>创建</Button></div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
