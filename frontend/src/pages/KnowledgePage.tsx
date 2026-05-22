import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, Plus, Search, UploadCloud, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
const fileTypes = ["", "pdf", "markdown", "txt", "image", "epub", "docx"];

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") as KnowledgeTab | null;
  const [activeTab, setActiveTab] = useState<KnowledgeTab>(requestedTab && tabs.some((tab) => tab.key === requestedTab) ? requestedTab : "documents");
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(searchParams.get("upload") === "1");
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
  const createCollectionMutation = useMutation({ mutationFn: createCollection, onSuccess: () => { setCollectionOpen(false); setCollectionForm({ name: "", description: "" }); queryClient.invalidateQueries({ queryKey: ["collections"] }); } });
  const documents = documentsQuery.data?.items ?? [];
  const total = documentsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function chooseTab(tab: KnowledgeTab) {
    setActiveTab(tab);
    setSearchParams(tab === "documents" ? {} : { tab });
  }

  function clearFilters() {
    setQuery(""); setTagId(""); setFileType(""); setStatus(""); setPage(1);
  }

  function submitCollection(event: FormEvent) {
    event.preventDefault();
    if (!collectionForm.name.trim()) return;
    createCollectionMutation.mutate({ name: collectionForm.name.trim(), description: collectionForm.description?.trim() || undefined });
  }

  return (
    <div className="space-y-5">
      <section className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div><div className="flex items-center gap-2"><h1 className="text-2xl font-semibold tracking-tight">知识库</h1><span className="text-2xl font-semibold text-slate-400">{statsQuery.data?.total_documents ?? total}</span></div><p className="mt-2 text-sm text-slate-500">集中管理资料、标签和集合，形成个人第二大脑。</p></div>
        <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" className="rounded-full px-4" onClick={() => setCollectionOpen(true)}><Plus className="h-4 w-4" />新建集合</Button><Button type="button" className="rounded-full bg-slate-950 px-5 text-white hover:bg-slate-800" onClick={() => setUploadOpen(true)}><UploadCloud className="h-4 w-4" />上传资料</Button></div>
      </section>
      <section className="min-h-[560px] rounded-[2rem] border border-slate-100 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap gap-2 border-b border-slate-100 pb-4">{tabs.map((item) => <button key={item.key} type="button" onClick={() => chooseTab(item.key)} className={cn("rounded-full px-4 py-2 text-sm font-medium transition", activeTab === item.key ? "bg-slate-950 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100")}>{item.label}</button>)}</div>
        {activeTab === "documents" && <>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(240px,1.6fr)_repeat(4,minmax(130px,1fr))]">
            <label className="relative block"><Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="搜索知识" className="h-11 w-full rounded-full border border-slate-200 bg-slate-50 pl-11 pr-4 text-sm outline-none transition focus:border-slate-300 focus:bg-white" /></label>
            <select value={tagId} onChange={(event) => { setTagId(event.target.value); setPage(1); }} className="h-11 rounded-full border border-slate-200 bg-white px-4 text-sm"><option value="">全部标签</option>{(tagsQuery.data ?? []).map((tag) => <option key={tag.id} value={tag.id}>#{tag.name}</option>)}</select>
            <select value={fileType} onChange={(event) => { setFileType(event.target.value); setPage(1); }} className="h-11 rounded-full border border-slate-200 bg-white px-4 text-sm">{fileTypes.map((type) => <option key={type || "all"} value={type}>{type ? type.toUpperCase() : "全部类型"}</option>)}</select>
            <select value={status} onChange={(event) => { setStatus(event.target.value as DocumentStatus | ""); setPage(1); }} className="h-11 rounded-full border border-slate-200 bg-white px-4 text-sm"><option value="">全部状态</option><option value="pending">等待解析</option><option value="processing">解析中</option><option value="done">已完成</option><option value="failed">失败</option></select>
            <Button type="button" variant="outline" className="rounded-full" onClick={clearFilters}>清空筛选</Button>
          </div>
          {documentsQuery.isLoading ? <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[...Array(6)].map((_, index) => <div key={index} className="h-44 animate-pulse rounded-3xl bg-slate-50" />)}</div> : documentsQuery.isError ? <div className="mt-24 text-center text-sm text-red-600">加载知识失败：{documentsQuery.error instanceof Error ? documentsQuery.error.message : "未知错误"}</div> : documents.length ? <section className="mt-8"><div className="mb-3 flex items-center justify-between gap-3 text-sm text-slate-600"><span className="flex items-center gap-2 font-semibold text-slate-700"><Library className="h-4 w-4" />文档知识 · {total} 个结果</span><span>第 {page} / {totalPages} 页</span></div><div className="grid gap-4">{documents.map((document) => <DocumentCard key={document.id} document={document} />)}</div><div className="mt-5 flex justify-end gap-2"><Button variant="outline" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>上一页</Button><Button variant="outline" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>下一页</Button></div></section> : <div className="flex min-h-[390px] flex-col items-center justify-center text-center"><h2 className="mt-5 text-xl font-semibold tracking-tight">还没有匹配资料</h2><p className="mt-2 text-sm text-slate-500">可以清空筛选，或上传第一份 PDF、EPUB、Markdown、图片等资料。</p><Button type="button" variant="outline" className="mt-5 rounded-full" onClick={() => setUploadOpen(true)}><UploadCloud className="h-4 w-4" />上传资料</Button></div>}
        </>}
        {activeTab === "collections" && <section className="mt-6"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold text-slate-700">集合</h2><Button size="sm" onClick={() => setCollectionOpen(true)}>新建集合</Button></div>{(collectionsQuery.data ?? []).length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{collectionsQuery.data?.map((collection) => <div key={collection.id} className="rounded-3xl border border-slate-100 bg-slate-50 p-4"><p className="font-medium text-slate-800">{collection.name}</p><p className="mt-1 line-clamp-2 text-sm text-slate-500">{collection.description || "暂无描述"}</p></div>)}</div> : <p className="rounded-2xl bg-slate-50 p-6 text-sm text-slate-500">还没有集合。集合用于归档同一主题的文档。</p>}</section>}
        {activeTab === "tags" && <section className="mt-6"><h2 className="mb-3 text-sm font-semibold text-slate-700">标签</h2>{(tagsQuery.data ?? []).length ? <div className="flex flex-wrap gap-2">{tagsQuery.data?.map((tag) => <TagPill key={tag.id} tag={tag} />)}</div> : <p className="rounded-2xl bg-slate-50 p-6 text-sm text-slate-500">还没有标签。请在文档详情或笔记中用 # 创建标签。</p>}</section>}
      </section>
      <WorkspaceUploadDialog open={uploadOpen} onOpenChange={(open) => { setUploadOpen(open); if (!open && searchParams.get("upload")) setSearchParams({}); }} />
      {collectionOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-modal="true"><form onSubmit={submitCollection} className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold tracking-tight">新建集合</h2><p className="mt-1 text-sm text-slate-500">创建一个集合，用来归档同一主题的文档。</p></div><Button type="button" variant="ghost" size="sm" onClick={() => setCollectionOpen(false)}><X className="h-4 w-4" /></Button></div><div className="mt-5 space-y-3"><label className="block"><span className="text-sm font-medium text-slate-700">名称</span><input value={collectionForm.name} onChange={(event) => setCollectionForm((current) => ({ ...current, name: event.target.value }))} className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-slate-500" placeholder="例如：论文、项目资料、读书笔记" /></label><label className="block"><span className="text-sm font-medium text-slate-700">描述</span><textarea value={collectionForm.description ?? ""} onChange={(event) => setCollectionForm((current) => ({ ...current, description: event.target.value }))} className="mt-1 min-h-24 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500" placeholder="这个集合用来收纳什么？" /></label>{createCollectionMutation.isError ? <p className="text-sm text-red-600">{createCollectionMutation.error.message}</p> : null}</div><div className="mt-5 flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setCollectionOpen(false)}>取消</Button><Button type="submit" disabled={!collectionForm.name.trim() || createCollectionMutation.isPending}>创建</Button></div></form></div>}
    </div>
  );
}