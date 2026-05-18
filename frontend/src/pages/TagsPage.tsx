import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit3, Plus, Save, Tag, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { batchTagDocuments, createTag, deleteTag, getDocuments, getTags, updateTag } from "@/lib/api";

export function TagsPage() {
  const queryClient = useQueryClient();
  const tags = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const documents = useQuery({ queryKey: ["documents", "tag-manager"], queryFn: () => getDocuments({ page: 1, size: 100 }) });
  const [name, setName] = useState("");
  const [color, setColor] = useState("#2563eb");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<number[]>([]);
  const [applyTagId, setApplyTagId] = useState("");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["tags"] });
    queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const createMutation = useMutation({
    mutationFn: createTag,
    onSuccess: () => {
      setName("");
      invalidate();
    }
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, nextName }: { id: number; nextName: string }) => updateTag(id, { name: nextName }),
    onSuccess: () => {
      setEditingId(null);
      setEditingName("");
      invalidate();
    }
  });
  const deleteMutation = useMutation({
    mutationFn: deleteTag,
    onSuccess: invalidate
  });
  const batchMutation = useMutation({
    mutationFn: ({ docIds, tagId }: { docIds: number[]; tagId: number }) => batchTagDocuments(docIds, [tagId]),
    onSuccess: () => {
      setSelectedDocumentIds([]);
      setApplyTagId("");
      invalidate();
    }
  });

  function toggleDocument(id: number) {
    setSelectedDocumentIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function submitTag() {
    if (!name.trim()) return;
    createMutation.mutate({ name: name.trim(), color });
  }

  function applyTag() {
    const tagId = Number(applyTagId);
    if (!tagId || !selectedDocumentIds.length) return;
    batchMutation.mutate({ docIds: selectedDocumentIds, tagId });
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Taxonomy</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Tags</h1>
        <p className="mt-2 text-sm text-slate-500">Create reusable tags and apply them to selected documents.</p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="grid gap-3 md:grid-cols-[1fr_160px_auto]">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="New tag name"
            className="h-10 rounded-md border border-slate-300 px-3 text-sm"
          />
          <input
            value={color}
            onChange={(event) => setColor(event.target.value)}
            type="color"
            className="h-10 w-full rounded-md border border-slate-300 bg-white p-1"
          />
          <Button onClick={submitTag} disabled={createMutation.isPending} className="gap-2">
            <Plus className="h-4 w-4" />
            Create
          </Button>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-200 p-4">
            <h2 className="font-semibold">Tag list</h2>
          </div>
          <div className="divide-y divide-slate-100">
            {(tags.data ?? []).map((tag) => (
              <div key={tag.id} className="flex items-center justify-between gap-3 p-4">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="h-3 w-3 rounded-full" style={{ backgroundColor: tag.color ?? "#2563eb" }} />
                  {editingId === tag.id ? (
                    <input
                      value={editingName}
                      onChange={(event) => setEditingName(event.target.value)}
                      className="h-9 rounded-md border border-slate-300 px-3 text-sm"
                    />
                  ) : (
                    <span className="font-medium">{tag.name}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  {editingId === tag.id ? (
                    <Button size="sm" variant="outline" onClick={() => updateMutation.mutate({ id: tag.id, nextName: editingName })}>
                      <Save className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => { setEditingId(tag.id); setEditingName(tag.name); }}>
                      <Edit3 className="h-4 w-4" />
                    </Button>
                  )}
                  <Button size="sm" variant="outline" className="text-red-600" onClick={() => deleteMutation.mutate(tag.id)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
            {!tags.isLoading && !(tags.data ?? []).length ? (
              <p className="p-4 text-sm text-slate-500">No tags yet.</p>
            ) : null}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-200 p-4">
            <h2 className="font-semibold">Batch tag documents</h2>
          </div>
          <div className="space-y-4 p-4">
            <select
              value={applyTagId}
              onChange={(event) => setApplyTagId(event.target.value)}
              className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
            >
              <option value="">Choose tag</option>
              {(tags.data ?? []).map((tag) => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
            </select>
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {(documents.data?.items ?? []).map((document) => (
                <label key={document.id} className="flex items-start gap-2 rounded-md border border-slate-200 p-3 text-sm">
                  <input
                    type="checkbox"
                    checked={selectedDocumentIds.includes(document.id)}
                    onChange={() => toggleDocument(document.id)}
                    className="mt-1"
                  />
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{document.title}</span>
                    <span className="block truncate text-slate-500">{document.original_filename}</span>
                  </span>
                </label>
              ))}
            </div>
            <Button onClick={applyTag} disabled={!applyTagId || !selectedDocumentIds.length || batchMutation.isPending} className="w-full gap-2">
              <Tag className="h-4 w-4" />
              Apply to {selectedDocumentIds.length} document(s)
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
