import { useQuery } from "@tanstack/react-query";
import {
  FileText,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { searchDocumentChunks } from "@/lib/api";
import { ChunkSearchHit } from "@/lib/types";

export function SearchPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQuery = searchParams.get("q") || "";
  const [query, setQuery] = useState(initialQuery);
  const [threshold, setThreshold] = useState(0.0);
  const [showFilters, setShowFilters] = useState(false);

  const trimmed = query.trim();
  const enabled = trimmed.length > 0;

  const { data, isLoading, error } = useQuery({
    queryKey: ["chunk-search", trimmed, threshold],
    queryFn: () => searchDocumentChunks(trimmed, 20, undefined, threshold),
    enabled,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (trimmed) {
      setSearchParams({ q: trimmed });
    }
  };

  const handleClear = () => {
    setQuery("");
    setSearchParams({});
  };

  const goToDocument = (documentId: number) => {
    navigate(`/documents/${documentId}`);
  };

  function formatScore(score: number) {
    return (score * 100).toFixed(1) + "%";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Semantic Search</h1>
        <p className="mt-2 text-sm text-slate-500">
          Search across document chunks using vector embeddings.
        </p>
      </div>

      <form onSubmit={handleSearch} className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search document chunks..."
            className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-10 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          />
          {query && (
            <button
              type="button"
              onClick={handleClear}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <Button type="submit" disabled={!trimmed || isLoading} className="gap-2">
          <Search className="h-4 w-4" />
          Search
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => setShowFilters(!showFilters)}
          className="gap-2"
        >
          <SlidersHorizontal className="h-4 w-4" />
          Filters
        </Button>
      </form>

      {showFilters && (
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-4">
              <label className="text-sm font-medium text-slate-700">
                Similarity threshold: {(threshold * 100).toFixed(0)}%
              </label>
              <input
                type="range"
                min="0"
                max="0.9"
                step="0.05"
                value={threshold}
                onChange={(e) => setThreshold(parseFloat(e.target.value))}
                className="w-48"
              />
              <span className="text-xs text-slate-500">
                Higher = fewer but more relevant results
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {!enabled && (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 p-12 text-center">
            <FileText className="h-12 w-12 text-slate-300" />
            <div>
              <p className="text-lg font-medium text-slate-900">Search document chunks</p>
              <p className="mt-1 text-sm text-slate-500">
                Enter a query above to search across all completed documents using vector similarity.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {isLoading && (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg bg-slate-100" />
          ))}
        </div>
      )}

      {error && (
        <Card>
          <CardContent className="p-6 text-sm text-red-600">
            {(error instanceof Error ? error.message : "An error occurred") as string}
          </CardContent>
        </Card>
      )}

      {data && data.items.length === 0 && (
        <Card>
          <CardContent className="p-6 text-sm text-slate-500">
            No matching chunks found. Try a different query or lower the similarity threshold.
          </CardContent>
        </Card>
      )}

      {data && data.items.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-slate-500">
            Found {data.total} result{data.total !== 1 ? "s" : ""}
          </p>
          {data.items.map((hit: ChunkSearchHit) => (
            <Card
              key={hit.id}
              className="cursor-pointer transition-shadow hover:shadow-md"
              onClick={() => goToDocument(hit.document_id)}
            >
              <CardContent className="p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-slate-900">{hit.filename || hit.document_title}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Chunk #{hit.chunk_index}
                      {hit.hash ? ` · ${hit.hash.slice(0, 12)}` : ""}
                    </p>
                    <p className="mt-1 text-sm text-slate-500 line-clamp-2">{hit.text}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1 text-xs text-slate-500">
                    <span
                      className={`rounded-full px-2 py-0.5 font-medium ${
                        hit.score >= 0.7
                          ? "bg-emerald-50 text-emerald-700"
                          : hit.score >= 0.5
                          ? "bg-amber-50 text-amber-700"
                          : "bg-slate-50 text-slate-600"
                      }`}
                    >
                      {formatScore(hit.score)}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5">
                      {hit.chunk_type}
                    </span>
                    {hit.page_start && (
                      <span>p. {hit.page_start}{hit.page_end && hit.page_end !== hit.page_start ? `-${hit.page_end}` : ""}</span>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
