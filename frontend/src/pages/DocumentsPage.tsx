import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { DocumentCard } from "@/components/DocumentCard";
import { Button } from "@/components/ui/button";
import { deleteDocument, getDocuments, retryDocumentParse, searchDocuments } from "@/lib/api";

const ITEMS_PER_PAGE = 20;

export function DocumentsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMode, setSearchMode] = useState<"keyword" | "hybrid">("keyword");

  const { data: response, isLoading, error } = useQuery({
    queryKey: ["documents", page],
    queryFn: () => getDocuments((page - 1) * ITEMS_PER_PAGE, ITEMS_PER_PAGE)
  });
  const trimmedSearch = searchQuery.trim();
  const searchEnabled = trimmedSearch.length > 0;
  const { data: searchResponse, isLoading: isSearching, error: searchError } = useQuery({
    queryKey: ["documents", "search", trimmedSearch, searchMode],
    queryFn: () => searchDocuments(trimmedSearch, 20, searchMode),
    enabled: searchEnabled
  });

  const retryMutation = useMutation({
    mutationFn: retryDocumentParse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  });

  const handleRetry = (documentId: number) => {
    retryMutation.mutate(documentId);
  };

  const handleDelete = (documentId: number) => {
    if (confirm("Are you sure you want to delete this document?")) {
      deleteMutation.mutate(documentId);
    }
  };

  const documents = response?.items || [];
  const searchResults = searchResponse?.items || [];
  const hasMore = documents.length === ITEMS_PER_PAGE;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Library</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">My Documents</h1>
          <p className="mt-2 text-sm text-slate-500">
            Manage your uploaded documents and knowledge base
          </p>
        </div>
        <Button
          size="lg"
          onClick={() => navigate("/upload")}
          className="gap-2"
        >
          <Plus className="h-5 w-5" />
          Upload Document
        </Button>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search title, cleaned text, OCR, chunks, or vector matches"
              className="h-10 w-full rounded-md border border-slate-300 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
            />
          </div>
          <div className="flex rounded-md border border-slate-200 p-1">
            <button
              type="button"
              onClick={() => setSearchMode("keyword")}
              className={`rounded px-3 py-1.5 text-sm font-medium ${searchMode === "keyword" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              Keyword
            </button>
            <button
              type="button"
              onClick={() => setSearchMode("hybrid")}
              className={`rounded px-3 py-1.5 text-sm font-medium ${searchMode === "hybrid" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              Hybrid
            </button>
          </div>
        </div>
        {searchEnabled && (
          <div className="mt-4 border-t border-slate-100 pt-4">
            {isSearching ? (
              <p className="text-sm text-slate-500">Searching...</p>
            ) : searchError ? (
              <p className="text-sm text-red-700">
                Search failed: {searchError instanceof Error ? searchError.message : "Unknown error"}
              </p>
            ) : searchResults.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {searchResponse?.total ?? 0} result{searchResponse?.total === 1 ? "" : "s"}
                </p>
                {searchResults.map((result) => (
                  <button
                    key={result.id}
                    type="button"
                    onClick={() => navigate(`/documents/${result.id}`)}
                    className="block w-full rounded-md border border-slate-200 p-3 text-left transition hover:border-blue-200 hover:bg-blue-50"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-medium text-slate-900">{result.title}</p>
                      <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">
                        {result.matched_field}
                        {searchMode === "hybrid" ? ` ${result.score.toFixed(2)}` : ""}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-slate-600">{result.snippet}</p>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No matches found.</p>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          Failed to load documents: {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-lg bg-slate-100"
            />
          ))}
        </div>
      ) : documents && documents.length > 0 ? (
        <>
          <div className="space-y-3">
            {documents.map((doc) => (
              <DocumentCard
                key={doc.id}
                document={doc}
                onRetry={handleRetry}
                onDelete={handleDelete}
                isRetrying={retryMutation.isPending && retryMutation.variables === doc.id}
                isDeleting={deleteMutation.isPending && deleteMutation.variables === doc.id}
              />
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between border-t border-slate-200 pt-4">
            <p className="text-sm text-slate-600">
              Page {page} {response?.total ? `(${response.total} total)` : ""}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                disabled={!hasMore}
                onClick={() => setPage(page + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-600">No documents yet</p>
          <p className="mt-2 text-xs text-slate-500">
            Upload your first document to get started
          </p>
          <Button
            className="mt-4"
            onClick={() => navigate("/upload")}
          >
            Upload Document
          </Button>
        </div>
      )}
    </div>
  );
}
