import { useQuery } from "@tanstack/react-query";
import { FileText, Filter, Library, Search, UploadCloud } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { WorkspaceUploadDialog } from "@/components/WorkspaceUploadDialog";
import { Button } from "@/components/ui/button";
import { getCollections, getDocuments, getStatistics, getTags } from "@/lib/api";
import { DocumentListItem, DocumentListParams } from "@/lib/types";
import { formatChinaDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";

type FilterKey = "all" | "documents" | "tags" | "collections" | "failed";

const filters: Array<{ key: FilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "documents", label: "文档" },
  { key: "tags", label: "标签" },
  { key: "collections", label: "集合" },
  { key: "failed", label: "失败" }
];

function KnowledgeCard({ document }: { document: DocumentListItem }) {
  return (
    <Link
      to={`/documents/${document.id}`}
      className="group block rounded-3xl border border-slate-100 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-200 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-50 text-slate-600 ring-1 ring-slate-100">
          <FileText className="h-5 w-5" />
        </span>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">{document.status}</span>
      </div>
      <h3 className="mt-4 line-clamp-2 font-semibold tracking-tight text-slate-950 group-hover:text-slate-700">{document.title}</h3>
      <p className="mt-2 line-clamp-2 text-sm text-slate-500">{document.content_summary || document.original_filename}</p>
      <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
        <span>{document.source_type}</span>
        <span>{formatChinaDateTime(document.uploaded_at)}</span>
      </div>
    </Link>
  );
}

export function KnowledgePage() {
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");
  const [uploadOpen, setUploadOpen] = useState(false);

  const documentParams: DocumentListParams = useMemo(() => ({
    page: 1,
    size: 24,
    keyword: query || undefined,
    status: activeFilter === "failed" ? "failed" : undefined,
    sort_by: "created_at",
    sort_order: "desc"
  }), [activeFilter, query]);

  const documentsQuery = useQuery({ queryKey: ["documents", "knowledge", documentParams], queryFn: () => getDocuments(documentParams) });
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const collectionsQuery = useQuery({ queryKey: ["collections"], queryFn: getCollections });
  const statsQuery = useQuery({ queryKey: ["statistics"], queryFn: getStatistics });

  const documents = documentsQuery.data?.items ?? [];
  const shouldShowDocuments = activeFilter === "all" || activeFilter === "documents" || activeFilter === "failed";
  const shouldShowTags = activeFilter === "all" || activeFilter === "tags";
  const shouldShowCollections = activeFilter === "all" || activeFilter === "collections";
  const hasVisibleDocuments = shouldShowDocuments && documents.length > 0;
  const hasVisibleTags = shouldShowTags && (tagsQuery.data?.length ?? 0) > 0;
  const hasVisibleCollections = shouldShowCollections && (collectionsQuery.data?.length ?? 0) > 0;
  const hasAnyKnowledge = hasVisibleDocuments || hasVisibleTags || hasVisibleCollections;

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
        <Button type="button" className="rounded-full bg-slate-950 px-5 text-white hover:bg-slate-800" onClick={() => setUploadOpen(true)}>
          + 创建知识库
        </Button>
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
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {documents.map((document) => <KnowledgeCard key={document.id} document={document} />)}
                </div>
              </section>
            ) : null}

            {hasVisibleTags ? (
              <section>
                <div className="mb-3 text-sm font-semibold text-slate-700">标签</div>
                <div className="flex flex-wrap gap-2">
                  {tagsQuery.data?.map((tag) => <span key={tag.id} className="rounded-full border border-slate-100 bg-slate-50 px-3 py-1.5 text-sm text-slate-600">#{tag.name}</span>)}
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
    </div>
  );
}
