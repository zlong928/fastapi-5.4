import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Filter, Library, Plus, Search, UploadCloud, X } from "lucide-react";
import { FormEvent } from "react";
import { useMemo, useState } from "react";
import { DocumentCard } from "@/components/DocumentCard";
import { TagPill, TagSelector } from "@/components/TagSelector";
import { WorkspaceUploadDialog } from "@/components/WorkspaceUploadDialog";
import { Button } from "@/components/ui/button";
import { createCollection, getCollections, getDocuments, getStatistics, getTags } from "@/lib/api";
import { CollectionCreate, DocumentListParams } from "@/lib/types";
import { cn } from "@/lib/utils";

type FilterKey = "all" | "documents" | "tags" | "collections" | "failed";

const filters: Array<{ key: FilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "documents", label: "文档" },
  { key: "tags", label: "标签" },
  { key: "collections", label: "集合" },
  { key: "failed", label: "失败" }
];

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [collectionForm, setCollectionForm] = useState<CollectionCreate>({ name: "", description: "" });
  const [tagId, setTagId] = useState("");

  const documentParams: DocumentListParams = useMemo(() => ({
    page: 1,
    size: 24,
    keyword: query || undefined,
    tag_id: tagId ? Number(tagId) : undefined,
    status: activeFilter === "failed" ? "failed" : undefined,
    sort_by: "created_at",
    sort_order: "desc"
  }), [activeFilter, query, tagId]);

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
  const shouldShowDocuments = activeFilter === "all" || activeFilter === "documents" || activeFilter === "failed";
  const shouldShowTags = activeFilter === "all" || activeFilter === "tags";
  const shouldShowCollections = activeFilter === "all" || activeFilter === "collections";
  const hasVisibleDocuments = shouldShowDocuments && documents.length > 0;
  const hasVisibleTags = shouldShowTags && (tagsQuery.data?.length ?? 0) > 0;
  const hasVisibleCollections = shouldShowCollections && (collectionsQuery.data?.length ?? 0) > 0;
  const hasAnyKnowledge = hasVisibleDocuments || hasVisibleTags || hasVisibleCollections;

  function submitCollection(event: FormEvent) {
    event.preventDefault();
    if (!collectionForm.name.trim()) return;
    createCollectionMutation.mutate({
      name: collectionForm.name.trim(),
      description: collectionForm.description?.trim() || undefined
    });
  }

  return (
    <div className="space-y-5">
      <section className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">知识库</h1>
            <span className="text-2xl font-semibold text-slate-400">{statsQuery.data?.total_documents ?? documentsQuery.data?.total ?? 0}</span>
          </div>
          <p className="mt-2 text-sm text-slate-500">集中管理上传资料、标签和集合，形成你的个人第二大脑。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" className="rounded-full px-4" onClick={() => setCollectionOpen(true)}>
            <Plus className="h-4 w-4" />
            新建知识库
          </Button>
          <Button type="button" className="rounded-full bg-slate-950 px-5 text-white hover:bg-slate-800" onClick={() => setUploadOpen(true)}>
            <UploadCloud className="h-4 w-4" />
            上传资料
          </Button>
        </div>
      </section>

      <section className="min-h-[560px] rounded-[2rem] border border-slate-100 bg-white p-4 shadow-sm">
        <div className="flex max-w-xl flex-col gap-3">
          <label className="relative block">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索知识"
              className="h-12 w-full rounded-full border border-transparent bg-slate-50 pl-11 pr-4 text-sm outline-none transition focus:border-slate-200 focus:bg-white"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            {filters.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setActiveFilter(item.key)}
                className={cn(
                  "inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm transition",
                  activeFilter === item.key ? "bg-slate-950 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"
                )}
              >
                {item.key === "all" ? <Filter className="h-4 w-4" /> : null}
                {item.label}
              </button>
            ))}
          </div>
          <select
            value={tagId}
            onChange={(event) => setTagId(event.target.value)}
            className="h-10 rounded-full border border-slate-200 bg-white px-4 text-sm text-slate-700 outline-none"
          >
            <option value="">按标签筛选：全部标签</option>
            {(tagsQuery.data ?? []).map((tag) => (
              <option key={tag.id} value={tag.id}>#{tag.name}</option>
            ))}
          </select>
        </div>

        {documentsQuery.isLoading ? (
          <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {[...Array(6)].map((_, index) => <div key={index} className="h-44 animate-pulse rounded-3xl bg-slate-50" />)}
          </div>
        ) : documentsQuery.isError ? (
          <div className="mt-24 text-center text-sm text-red-600">加载知识失败：{documentsQuery.error instanceof Error ? documentsQuery.error.message : "未知错误"}</div>
        ) : hasAnyKnowledge ? (
          <div className="mt-8 space-y-8">
            {hasVisibleDocuments ? (
              <section>
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700"><Library className="h-4 w-4" />文档知识</div>
                <div className="grid gap-4">
                  {documents.map((document) => (
                    <div key={document.id} className="space-y-2">
                      <DocumentCard document={document} />
                      <TagSelector documentIds={[document.id]} compact />
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {hasVisibleTags ? (
              <section>
                <div className="mb-3 text-sm font-semibold text-slate-700">标签</div>
                <div className="flex flex-wrap gap-2">
                  {tagsQuery.data?.map((tag) => <TagPill key={tag.id} tag={tag} />)}
                </div>
              </section>
            ) : null}

            {hasVisibleCollections ? (
              <section>
                <div className="mb-3 text-sm font-semibold text-slate-700">集合</div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {collectionsQuery.data?.map((collection) => (
                    <div key={collection.id} className="rounded-3xl border border-slate-100 bg-slate-50 p-4">
                      <p className="font-medium text-slate-800">{collection.name}</p>
                      <p className="mt-1 line-clamp-2 text-sm text-slate-500">{collection.description || "暂无描述"}</p>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        ) : (
          <div className="flex min-h-[390px] flex-col items-center justify-center text-center">
            <div className="text-4xl">🙁</div>
            <h2 className="mt-5 text-xl font-semibold tracking-tight">未找到知识</h2>
            <p className="mt-2 text-sm text-slate-500">请尝试调整您的搜索词或过滤器以找到您需要的内容。</p>
            <Button type="button" variant="outline" className="mt-5 rounded-full" onClick={() => setUploadOpen(true)}>
              <UploadCloud className="h-4 w-4" />
              上传第一份资料
            </Button>
          </div>
        )}
      </section>

      <WorkspaceUploadDialog open={uploadOpen} onOpenChange={setUploadOpen} />
      {collectionOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-modal="true">
          <form onSubmit={submitCollection} className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">新建知识库</h2>
                <p className="mt-1 text-sm text-slate-500">创建一个集合，用来归档同一主题的文档。</p>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={() => setCollectionOpen(false)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="mt-5 space-y-3">
              <label className="block">
                <span className="text-sm font-medium text-slate-700">名称</span>
                <input
                  value={collectionForm.name}
                  onChange={(event) => setCollectionForm((current) => ({ ...current, name: event.target.value }))}
                  className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 text-sm outline-none focus:border-slate-500"
                  placeholder="例如：论文、项目资料、读书笔记"
                />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-slate-700">描述</span>
                <textarea
                  value={collectionForm.description ?? ""}
                  onChange={(event) => setCollectionForm((current) => ({ ...current, description: event.target.value }))}
                  className="mt-1 min-h-24 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
                  placeholder="这个知识库用来收纳什么？"
                />
              </label>
              {createCollectionMutation.isError ? (
                <p className="text-sm text-red-600">{createCollectionMutation.error.message}</p>
              ) : null}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setCollectionOpen(false)}>取消</Button>
              <Button type="submit" disabled={!collectionForm.name.trim() || createCollectionMutation.isPending}>创建</Button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
