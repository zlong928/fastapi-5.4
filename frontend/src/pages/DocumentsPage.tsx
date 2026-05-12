import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { DocumentCard } from "@/components/DocumentCard";
import { Button } from "@/components/ui/button";
import { deleteDocument, getDocuments, retryDocumentParse } from "@/lib/api";

const ITEMS_PER_PAGE = 20;

export function DocumentsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);

  const { data: response, isLoading, error } = useQuery({
    queryKey: ["documents", page],
    queryFn: () => getDocuments((page - 1) * ITEMS_PER_PAGE, ITEMS_PER_PAGE)
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
