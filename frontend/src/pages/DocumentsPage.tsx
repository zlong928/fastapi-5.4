import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, RefreshCw, Search, Tag, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DocumentCard } from "@/components/DocumentCard";
import { Button } from "@/components/ui/button";
import { batchDeleteDocuments, batchTagDocuments, deleteDocument, getDocuments, getTags, retryDocumentParse } from "@/lib/api";
import { DocumentListParams, DocumentStatus } from "@/lib/types";

const ITEMS_PER_PAGE = 10;

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [filters, setFilters] = useState<DocumentListParams>({
    page: 1,
    size: ITEMS_PER_PAGE,
    sort_by: "created_at",
    sort_order: "desc"
  });
  const [selectedTagId, setSelectedTagId] = useState("");

  const queryParams = useMemo(() => ({ ...filters, page, size: ITEMS_PER_PAGE }), [filters, page]);
  const documentsQuery = useQuery({
    queryKey: ["documents", queryParams],
    queryFn: () => getDocuments(queryParams),
    refetchInterval: (query) => {
      const docs = query.state.data?.items ?? [];
      return docs.some((doc) => ["pending", "processing"].includes(doc.status)) ? 2000 : false;
    }
  });
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });

  const retryMutation = useMutation({
    mutationFn: retryDocumentParse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] })
  });

  const batchDeleteMutation = useMutation({
    mutationFn: batchDeleteDocuments,
    onSuccess: () => {
      setSelectedIds([]);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  });

  const batchTagMutation = useMutation({
    mutationFn: ({ documentIds, tagIds }: { documentIds: number[]; tagIds: number[] }) => batchTagDocuments(documentIds, tagIds),
    onSuccess: () => {
      setSelectedIds([]);
      setSelectedTagId("");
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  });

  const documents = documentsQuery.data?.items ?? [];
  const total = documentsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / ITEMS_PER_PAGE));
  const allVisibleSelected = documents.length > 0 && documents.every((document) => selectedIds.includes(document.id));

  function updateFilter<K extends keyof DocumentListParams>(key: K, value: DocumentListParams[K]) {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function toggleSelected(documentId: number) {
    setSelectedIds((current) =>
      current.includes(documentId) ? current.filter((id) => id !== documentId) : [...current, documentId]
    );
  }

  function toggleVisibleSelected() {
    if (allVisibleSelected) {
      setSelectedIds((current) => current.filter((id) => !documents.some((document) => document.id === id)));
      return;
    }
    setSelectedIds((current) => Array.from(new Set([...current, ...documents.map((document) => document.id)])));
  }

  function runBatchDelete() {
    if (!selectedIds.length) return;
    if (confirm(`Delete ${selectedIds.length} selected document(s)?`)) {
      batchDeleteMutation.mutate(selectedIds);
    }
  }

  function runBatchTag() {
    const tagId = Number(selectedTagId);
    if (!selectedIds.length || !tagId) return;
    batchTagMutation.mutate({ documentIds: selectedIds, tagIds: [tagId] });
  }

  function clearFilters() {
    setFilters({ page: 1, size: ITEMS_PER_PAGE, sort_by: "created_at", sort_order: "desc" });
    setPage(1);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Knowledge Base</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Documents</h1>
          <p className="mt-2 text-sm text-slate-500">Search, filter, retry, tag, and manage private knowledge documents.</p>
        </div>
        <Button asChild className="gap-2">
          <Link to="/upload">
            <FileUp className="h-4 w-4" />
            Upload
          </Link>
        </Button>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="md:col-span-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Keyword</span>
            <div className="relative mt-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={filters.keyword ?? ""}
                onChange={(event) => updateFilter("keyword", event.target.value)}
                placeholder="Title, filename, or parsed text"
                className="h-10 w-full rounded-md border border-slate-300 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tag</span>
            <select
              value={filters.tag_id ?? ""}
              onChange={(event) => updateFilter("tag_id", event.target.value ? Number(event.target.value) : undefined)}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="">All tags</option>
              {(tagsQuery.data ?? []).map((tag) => (
                <option key={tag.id} value={tag.id}>{tag.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</span>
            <select
              value={filters.status ?? ""}
              onChange={(event) => updateFilter("status", event.target.value as DocumentStatus | "")}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="processing">Processing</option>
              <option value="done">Done</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">File type</span>
            <select
              value={filters.file_type ?? ""}
              onChange={(event) => updateFilter("file_type", event.target.value as DocumentListParams["file_type"])}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="">All types</option>
              <option value="pdf">PDF</option>
              <option value="markdown">Markdown</option>
              <option value="txt">TXT</option>
            </select>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Start date</span>
            <input
              type="date"
              value={filters.start_date ?? ""}
              onChange={(event) => updateFilter("start_date", event.target.value || undefined)}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
            />
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">End date</span>
            <input
              type="date"
              value={filters.end_date ?? ""}
              onChange={(event) => updateFilter("end_date", event.target.value || undefined)}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
            />
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sort</span>
            <select
              value={`${filters.sort_by}:${filters.sort_order}`}
              onChange={(event) => {
                const [sortBy, sortOrder] = event.target.value.split(":");
                setFilters((current) => ({ ...current, sort_by: sortBy as DocumentListParams["sort_by"], sort_order: sortOrder as "asc" | "desc" }));
              }}
              className="mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="created_at:desc">Newest first</option>
              <option value="created_at:asc">Oldest first</option>
              <option value="title:asc">Title A-Z</option>
              <option value="file_size:desc">Largest first</option>
              <option value="status:asc">Status</option>
            </select>
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
          <p className="text-sm text-slate-500">{total} document(s)</p>
          <Button type="button" variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>
        </div>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={allVisibleSelected} onChange={toggleVisibleSelected} />
          Select visible
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-slate-500">{selectedIds.length} selected</span>
          <select
            value={selectedTagId}
            onChange={(event) => setSelectedTagId(event.target.value)}
            className="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            <option value="">Choose tag</option>
            {(tagsQuery.data ?? []).map((tag) => (
              <option key={tag.id} value={tag.id}>{tag.name}</option>
            ))}
          </select>
          <Button type="button" size="sm" variant="outline" onClick={runBatchTag} disabled={!selectedIds.length || !selectedTagId || batchTagMutation.isPending} className="gap-2">
            <Tag className="h-4 w-4" />
            Apply tag
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={runBatchDelete} disabled={!selectedIds.length || batchDeleteMutation.isPending} className="gap-2 text-red-600">
            <Trash2 className="h-4 w-4" />
            Delete
          </Button>
        </div>
      </section>

      {documentsQuery.error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Failed to load documents: {documentsQuery.error instanceof Error ? documentsQuery.error.message : "Unknown error"}
        </div>
      )}

      {documentsQuery.isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => <div key={i} className="h-24 animate-pulse rounded-lg bg-slate-100" />)}
        </div>
      ) : documents.length > 0 ? (
        <div className="space-y-3">
          {documents.map((doc) => (
            <div key={doc.id} className="grid gap-3 md:grid-cols-[24px_minmax(0,1fr)] md:items-start">
              <input
                type="checkbox"
                checked={selectedIds.includes(doc.id)}
                onChange={() => toggleSelected(doc.id)}
                className="mt-5"
                aria-label={`Select ${doc.title}`}
              />
              <DocumentCard
                document={doc}
                onRetry={(documentId) => retryMutation.mutate(documentId)}
                onDelete={(documentId) => {
                  if (confirm("Delete this document?")) deleteMutation.mutate(documentId);
                }}
                isRetrying={retryMutation.isPending && retryMutation.variables === doc.id}
                isDeleting={deleteMutation.isPending && deleteMutation.variables === doc.id}
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-600">No documents match the current filters.</p>
          <Button asChild className="mt-4">
            <Link to="/upload">Upload documents</Link>
          </Button>
        </div>
      )}

      <div className="flex items-center justify-between border-t border-slate-200 pt-4">
        <p className="text-sm text-slate-600">Page {page} of {totalPages}</p>
        <div className="flex gap-2">
          <Button variant="outline" disabled={page === 1} onClick={() => setPage((current) => current - 1)}>Previous</Button>
          <Button variant="outline" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>Next</Button>
          <Button variant="outline" onClick={() => queryClient.invalidateQueries({ queryKey: ["documents"] })} className="gap-2">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>
      </div>
    </div>
  );
}
