import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FolderOpen, Library, Link2, MoreHorizontal, Plus, Search, Trash2, UploadCloud, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BookmarkSaveDialog } from "@/components/BookmarkSaveDialog";
import { DocumentCard } from "@/components/DocumentCard";
import { TagPill } from "@/components/TagSelector";
import { WorkspaceUploadDialog } from "@/components/WorkspaceUploadDialog";
import { Button } from "@/components/ui/button";
import { API_BASE_URL, createCollection, getCollections, getDocuments, getStatistics, getTags, getToken, updateDocument } from "@/lib/api";
import { CollectionCreate, CollectionRead, DocumentListItem, DocumentListParams, DocumentListResponse, DocumentStatus, MessageResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

type KnowledgeTab = "documents" | "collections" | "tags";
type CollectionMode = "create" | "edit";

const PAGE_SIZE = 12;
const tabs: Array<{ key: KnowledgeTab; label: string }> = [
  { key: "documents", label: "文档" },
  { key: "collections", label: "集合" },
  { key: "tags", label: "标签" }
];
const fileTypes = ["", "pdf", "markdown", "txt", "image", "epub", "docx", "bookmark"];
const fileTypeLabels: Record<string, string> = { pdf: "PDF", markdown: "Markdown", txt: "TXT", image: "图片", epub: "EPUB", docx: "DOCX", bookmark: "链接" };

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json", ...init?.headers });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try { const payload = await response.json(); if (payload?.detail) message = payload.detail; } catch { message = response.statusText || message; }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function paramsToQuery(params: DocumentListParams) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== "") search.set(key, String(value)); });
  const query = search.toString();
  return query ? `?${query}` : "";
}

function updateCollection(collectionId: number, payload: CollectionCreate) {
  return requestJson<CollectionRead>(`/collections/${collectionId}`, { method: "PATCH", body: JSON.stringify(payload) });
}
function deleteCollection(collectionId: number) {
  return requestJson<MessageResponse>(`/collections/${collectionId}`, { method: "DELETE" });
}
function getCollectionDocuments(collectionId: number, params: DocumentListParams) {
  return requestJson<DocumentListResponse>(`/collections/${collectionId}/documents${paramsToQuery(params)}`);
}
function addDocumentToCollection(collectionId: number, documentId: number) {
  return requestJson<MessageResponse>(`/collections/${collectionId}/documents/${documentId}`, { method: "POST" });
}
function removeDocumentFromCollection(collectionId: number, documentId: number) {
  return requestJson<MessageResponse>(`/collections/${collectionId}/documents/${documentId}`, { method: "DELETE" });
}

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") as KnowledgeTab | null;
  const [activeTab, setActiveTab] = useState<KnowledgeTab>(requestedTab && tabs.some((tab) => tab.key === requestedTab) ? requestedTab : "documents");
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(searchParams.get("upload") === "1");
  const [bookmarkOpen, setBookmarkOpen] = useState(false);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [collectionMode, setCollectionMode] = useState<CollectionMode>("create");
  const [editingCollection, setEditingCollection] = useState<CollectionRead | null>(null);
  const [selectedCollection, setSelectedCollection] = useState<CollectionRead | null>(null);
  const [collectionFilter, setCollectionFilter] = useState("");
  const [movingDocument, setMovingDocument] = useState<DocumentListItem | null>(null);
  const [targetCollectionId, setTargetCollectionId] = useState("");
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

  const collectionsQuery = useQuery({ queryKey: ["collections"], queryFn: getCollections });
  const selectedFilterCollection = (collectionsQuery.data ?? []).find((collection) => String(collection.id) === collectionFilter);
  const documentsQuery = useQuery({
    queryKey: ["documents", "knowledge", documentParams, collectionFilter],
    queryFn: () => selectedFilterCollection ? getCollectionDocuments(selectedFilterCollection.id, documentParams) : getDocuments(documentParams)
  });
  const collectionDocumentsQuery = useQuery({
    queryKey: ["collection-documents", selectedCollection?.id, documentParams],
    queryFn: () => selectedCollection ? getCollectionDocuments(selectedCollection.id, documentParams) : Promise.resolve({ total: 0, page: 1, size: PAGE_SIZE, items: [] }),
    enabled: Boolean(selectedCollection)
  });
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const statsQuery = useQuery({ queryKey: ["statistics"], queryFn: getStatistics });

  const createCollectionMutation = useMutation({ mutationFn: createCollection, onSuccess: () => closeCollectionDialog(true) });
  const updateCollectionMutation = useMutation({ mutationFn: ({ id, payload }: { id: number; payload: CollectionCreate }) => updateCollection(id, payload), onSuccess: (collection) => { setSelectedCollection(collection); closeCollectionDialog(true); } });
  const deleteCollectionMutation = useMutation({ mutationFn: deleteCollection, onSuccess: () => { setSelectedCollection(null); setCollectionFilter(""); invalidateKnowledge(); } });
  const addDocumentMutation = useMutation({ mutationFn: ({ collectionId, documentId }: { collectionId: number; documentId: number }) => addDocumentToCollection(collectionId, documentId), onSuccess: () => { setMovingDocument(null); setTargetCollectionId(""); invalidateKnowledge(); } });
  const removeDocumentMutation = useMutation({ mutationFn: ({ collectionId, documentId }: { collectionId: number; documentId: number }) => removeDocumentFromCollection(collectionId, documentId), onSuccess: invalidateKnowledge });
  const clearCollectionMutation = useMutation({ mutationFn: (documentId: number) => updateDocument(documentId, { collection_name: null }), onSuccess: invalidateKnowledge });

  const documents = documentsQuery.data?.items ?? [];
  const tags = tagsQuery.data ?? [];
  const collections = collectionsQuery.data ?? [];
  const total = documentsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasFilters = Boolean(query || tagId || fileType || status || collectionFilter);
  const documentsErrorMessage = documentsQuery.error instanceof Error ? documentsQuery.error.message : "加载失败";

  function invalidateKnowledge() {
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    queryClient.invalidateQueries({ queryKey: ["collections"] });
    queryClient.invalidateQueries({ queryKey: ["collection-documents"] });
    queryClient.invalidateQueries({ queryKey: ["statistics"] });
  }

  function chooseTab(tab: KnowledgeTab) { setActiveTab(tab); setSearchParams(tab === "documents" ? {} : { tab }); }
  function clearFilters() { setQuery(""); setTagId(""); setFileType(""); setStatus(""); setCollectionFilter(""); setPage(1); }
  function openCreateCollection() { setCollectionMode("create"); setEditingCollection(null); setCollectionForm({ name: "", description: "" }); setCollectionOpen(true); }
  function openEditCollection(collection: CollectionRead) { setCollectionMode("edit"); setEditingCollection(collection); setCollectionForm({ name: collection.name, description: collection.description ?? "" }); setCollectionOpen(true); }
  function closeCollectionDialog(refresh = false) { setCollectionOpen(false); setEditingCollection(null); setCollectionMode("create"); setCollectionForm({ name: "", description: "" }); if (refresh) invalidateKnowledge(); }
  function submitCollection(event: FormEvent) { event.preventDefault(); const payload = { name: collectionForm.name.trim(), description: collectionForm.description?.trim() || undefined }; if (!payload.name) return; if (collectionMode === "edit" && editingCollection) updateCollectionMutation.mutate({ id: editingCollection.id, payload }); else createCollectionMutation.mutate(payload); }
  function confirmDeleteCollection(collection: CollectionRead) { if (window.confirm(`删除集合「${collection.name}」？文档不会被删除，只会移出该集合。`)) deleteCollectionMutation.mutate(collection.id); }
  function openMoveDialog(document: DocumentListItem) { setMovingDocument(document); const current = collections.find((collection) => collection.name === document.collection_name); setTargetCollectionId(current ? String(current.id) : ""); }
  function submitMoveDocument(event: FormEvent) { event.preventDefault(); if (!movingDocument) return; if (!targetCollectionId) { clearCollectionMutation.mutate(movingDocument.id); setMovingDocument(null); return; } addDocumentMutation.mutate({ collectionId: Number(targetCollectionId), documentId: movingDocument.id }); }

  const collectionDetailDocs = collectionDocumentsQuery.data?.items ?? [];
  const collectionDetailTotal = collectionDocumentsQuery.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <section className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="flex items-center gap-2"><h1 className="text-2xl font-semibold tracking-tight">知识库</h1><span className="rounded-full bg-slate-100 px-2.5 py-1 text-sm font-medium text-slate-500">{statsQuery.data?.total_documents ?? total}</span></div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={openCreateCollection}><Plus className="h-4 w-4" />新建集合</Button>
          <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={() => setBookmarkOpen(true)}><Link2 className="h-4 w-4" />保存链接</Button>
          <Button type="button" size="sm" className="rounded-xl bg-slate-950 text-white hover:bg-slate-800" onClick={() => setUploadOpen(true)}><UploadCloud className="h-4 w-4" />上传</Button>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-4">
          <div className="rounded-3xl border border-slate-100 bg-white p-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
              <label className="relative block flex-1"><Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="搜索资料" className="h-11 w-full rounded-2xl border border-transparent bg-slate-50 pl-11 pr-4 text-sm outline-none transition focus:border-slate-200 focus:bg-white" /></label>
              <div className="flex shrink-0 gap-1 rounded-2xl bg-slate-50 p-1">{tabs.map((item) => <button key={item.key} type="button" onClick={() => chooseTab(item.key)} className={cn("rounded-xl px-3 py-2 text-sm font-medium text-slate-500 transition hover:text-slate-950", activeTab === item.key && "bg-white text-slate-950 ring-1 ring-slate-100")}>{item.label}</button>)}</div>
            </div>
            {activeTab === "documents" ? <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
              <select value={collectionFilter} onChange={(event) => { setCollectionFilter(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none"><option value="">全部集合</option>{collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}</select>
              <select value={tagId} onChange={(event) => { setTagId(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none"><option value="">全部标签</option>{tags.map((tag) => <option key={tag.id} value={tag.id}>#{tag.name}</option>)}</select>
              <select value={fileType} onChange={(event) => { setFileType(event.target.value); setPage(1); }} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none">{fileTypes.map((type) => <option key={type || "all"} value={type}>{type ? fileTypeLabels[type] ?? type.toUpperCase() : "全部类型"}</option>)}</select>
              <select value={status} onChange={(event) => { setStatus(event.target.value as DocumentStatus | ""); setPage(1); }} className="h-9 rounded-xl border border-slate-100 bg-white px-3 text-sm text-slate-600 outline-none"><option value="">全部状态</option><option value="pending">等待</option><option value="processing">解析中</option><option value="done">完成</option><option value="failed">失败</option></select>
              {hasFilters ? <Button type="button" variant="ghost" size="sm" className="h-9 rounded-xl text-slate-500" onClick={clearFilters}>清空</Button> : null}
            </div> : null}
          </div>

          {activeTab === "documents" ? <section className="rounded-3xl border border-slate-100 bg-white p-3"><div className="mb-2 flex items-center justify-between px-1 text-sm text-slate-500"><span className="flex items-center gap-2 font-medium text-slate-700"><Library className="h-4 w-4" />资料 · {total}</span><span>{page} / {totalPages}</span></div>{documentsQuery.isLoading ? <div className="space-y-2">{[...Array(7)].map((_, index) => <div key={index} className="h-20 animate-pulse rounded-2xl bg-slate-50" />)}</div> : documentsQuery.isError ? <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-red-100 bg-red-50 px-4 text-center text-sm text-red-600">加载失败：{documentsErrorMessage}</div> : documents.length ? <><div className="space-y-2">{documents.map((document) => <DocumentCard key={document.id} document={document} onMoveToCollection={openMoveDialog} />)}</div><div className="mt-4 flex justify-end gap-2"><Button variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>上一页</Button><Button variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>下一页</Button></div></> : <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-slate-50 text-sm text-slate-400">无文档</div>}</section> : null}

          {activeTab === "collections" ? <section className="rounded-3xl border border-slate-100 bg-white p-4">{selectedCollection ? <div className="space-y-3"><div className="flex flex-wrap items-start justify-between gap-3"><div><Button type="button" variant="ghost" size="sm" className="mb-2 rounded-xl text-slate-500" onClick={() => setSelectedCollection(null)}><ArrowLeft className="h-4 w-4" />返回集合</Button><h2 className="text-lg font-semibold text-slate-900">{selectedCollection.name}</h2><p className="mt-1 text-sm text-slate-500">{selectedCollection.description || "暂无描述"}</p></div><div className="flex gap-2"><Button size="sm" variant="outline" className="rounded-xl border-slate-100" onClick={() => openEditCollection(selectedCollection)}>编辑</Button><Button size="sm" variant="ghost" className="rounded-xl text-red-500" onClick={() => confirmDeleteCollection(selectedCollection)}>删除</Button></div></div><div className="rounded-2xl border border-slate-100 bg-slate-50/60 p-3"><p className="mb-2 text-sm font-medium text-slate-700">集合文档 · {collectionDetailTotal}</p>{collectionDocumentsQuery.isLoading ? <div className="h-24 animate-pulse rounded-xl bg-white" /> : collectionDetailDocs.length ? <div className="space-y-2">{collectionDetailDocs.map((document) => <div key={document.id} className="rounded-2xl bg-white"><DocumentCard document={document} onMoveToCollection={openMoveDialog} /><div className="flex justify-end border-t border-slate-50 px-3 py-2"><Button size="sm" variant="ghost" className="rounded-xl text-slate-500" disabled={removeDocumentMutation.isPending} onClick={() => removeDocumentMutation.mutate({ collectionId: selectedCollection.id, documentId: document.id })}>从集合移除</Button></div></div>)}</div> : <div className="flex min-h-[180px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-white text-sm text-slate-400">这个集合还没有资料，可从文档卡片加入集合</div>}</div></div> : <><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold text-slate-700">集合</h2><Button size="sm" className="rounded-xl" onClick={openCreateCollection}>新建集合</Button></div>{collections.length ? <div className="grid gap-2 md:grid-cols-2">{collections.map((collection) => <article key={collection.id} className="group rounded-2xl border border-slate-100 bg-slate-50/70 p-4 transition hover:border-slate-200 hover:bg-white"><button type="button" className="block w-full text-left" onClick={() => setSelectedCollection(collection)}><div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2"><FolderOpen className="h-4 w-4 text-slate-400" /><p className="font-medium text-slate-800">{collection.name}</p></div><span className="rounded-full bg-white px-2 py-0.5 text-xs text-slate-500">{collection.document_count ?? 0} 篇</span></div><p className="mt-2 line-clamp-2 text-sm text-slate-500">{collection.description || "暂无描述"}</p></button><div className="mt-3 flex justify-end gap-1 opacity-100 md:opacity-0 md:transition md:group-hover:opacity-100"><Button size="sm" variant="ghost" className="rounded-xl" onClick={() => openEditCollection(collection)}><MoreHorizontal className="h-4 w-4" />编辑</Button><Button size="sm" variant="ghost" className="rounded-xl text-red-500" onClick={() => confirmDeleteCollection(collection)}><Trash2 className="h-4 w-4" />删除</Button></div></article>)}</div> : <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-slate-50 text-sm text-slate-400">无集合</div>}</>}</section> : null}

          {activeTab === "tags" ? <section className="rounded-3xl border border-slate-100 bg-white p-4"><h2 className="mb-3 text-sm font-semibold text-slate-700">标签</h2>{tags.length ? <div className="flex flex-wrap gap-2">{tags.map((tag) => <TagPill key={tag.id} tag={tag} />)}</div> : <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-slate-100 bg-slate-50 text-sm text-slate-400">无标签</div>}</section> : null}
        </div>

        <aside className="hidden space-y-3 xl:block"><div className="rounded-3xl border border-slate-100 bg-white p-4"><p className="text-sm font-semibold text-slate-800">概览</p><div className="mt-4 grid grid-cols-2 gap-2 text-sm"><div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">资料</p><p className="mt-1 text-xl font-semibold">{statsQuery.data?.total_documents ?? total}</p></div><div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">失败</p><p className="mt-1 text-xl font-semibold text-red-500">{statsQuery.data?.failed_documents ?? 0}</p></div><div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">集合</p><p className="mt-1 text-xl font-semibold">{collections.length}</p></div><div className="rounded-2xl bg-slate-50 p-3"><p className="text-xs text-slate-400">标签</p><p className="mt-1 text-xl font-semibold">{tags.length}</p></div></div></div><div className="rounded-3xl border border-slate-100 bg-white p-4"><p className="text-sm font-semibold text-slate-800">常用标签</p><div className="mt-3 flex flex-wrap gap-2">{tags.slice(0, 12).map((tag) => <TagPill key={tag.id} tag={tag} />)}{!tags.length ? <p className="text-sm text-slate-500">无标签</p> : null}</div></div></aside>
      </section>

      <WorkspaceUploadDialog open={uploadOpen} onOpenChange={(open) => { setUploadOpen(open); if (!open && searchParams.get("upload")) setSearchParams({}); }} />
      <BookmarkSaveDialog open={bookmarkOpen} onOpenChange={setBookmarkOpen} />

      {collectionOpen ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-modal="true"><form onSubmit={submitCollection} className="w-full max-w-lg rounded-3xl bg-white p-5 shadow-xl"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold tracking-tight">{collectionMode === "edit" ? "编辑集合" : "新建集合"}</h2></div><Button type="button" variant="ghost" size="sm" className="rounded-xl" onClick={() => closeCollectionDialog()}><X className="h-4 w-4" /></Button></div><div className="mt-5 space-y-3"><label className="block"><span className="text-sm font-medium text-slate-700">名称</span><input value={collectionForm.name} onChange={(event) => setCollectionForm((current) => ({ ...current, name: event.target.value }))} className="mt-1 h-10 w-full rounded-xl border border-slate-100 px-3 text-sm outline-none focus:border-slate-300" placeholder="集合名称" /></label><label className="block"><span className="text-sm font-medium text-slate-700">描述</span><textarea value={collectionForm.description ?? ""} onChange={(event) => setCollectionForm((current) => ({ ...current, description: event.target.value }))} className="mt-1 min-h-24 w-full rounded-xl border border-slate-100 px-3 py-2 text-sm outline-none focus:border-slate-300" placeholder="可选" /></label>{createCollectionMutation.isError ? <p className="text-sm text-red-600">{createCollectionMutation.error.message}</p> : null}{updateCollectionMutation.isError ? <p className="text-sm text-red-600">{updateCollectionMutation.error.message}</p> : null}</div><div className="mt-5 flex justify-end gap-2"><Button type="button" variant="outline" className="rounded-xl border-slate-100 shadow-none" onClick={() => closeCollectionDialog()}>取消</Button><Button type="submit" className="rounded-xl" disabled={!collectionForm.name.trim() || createCollectionMutation.isPending || updateCollectionMutation.isPending}>{collectionMode === "edit" ? "保存" : "创建"}</Button></div></form></div> : null}

      {movingDocument ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-modal="true"><form onSubmit={submitMoveDocument} className="w-full max-w-md rounded-3xl bg-white p-5 shadow-xl"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold tracking-tight">移动到集合</h2><p className="mt-1 text-sm text-slate-500 line-clamp-1">{movingDocument.title}</p></div><Button type="button" variant="ghost" size="sm" className="rounded-xl" onClick={() => setMovingDocument(null)}><X className="h-4 w-4" /></Button></div><select value={targetCollectionId} onChange={(event) => setTargetCollectionId(event.target.value)} className="mt-5 h-10 w-full rounded-xl border border-slate-100 bg-white px-3 text-sm outline-none focus:border-slate-300"><option value="">不放入集合</option>{collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}</select><p className="mt-2 text-xs text-slate-400">选择新集合会覆盖当前集合。</p><div className="mt-5 flex justify-end gap-2"><Button type="button" variant="outline" className="rounded-xl border-slate-100 shadow-none" onClick={() => setMovingDocument(null)}>取消</Button><Button type="submit" className="rounded-xl" disabled={addDocumentMutation.isPending || clearCollectionMutation.isPending}>确认</Button></div></form></div> : null}
    </div>
  );
}
