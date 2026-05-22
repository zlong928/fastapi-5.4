import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Tag as TagIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { batchTagDocuments, createTag, getTags } from "@/lib/api";
import { TagRead } from "@/lib/types";

export function TagPill({ tag }: { tag: TagRead }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-100 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tag.color ?? "#2563eb" }} />
      #{tag.name}
    </span>
  );
}

export function TagSelector({ documentIds, compact = false }: { documentIds: number[]; compact?: boolean }) {
  const queryClient = useQueryClient();
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const [tagId, setTagId] = useState("");
  const [newTagName, setNewTagName] = useState("");

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["tags"] });
    queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const applyMutation = useMutation({
    mutationFn: (nextTagId: number) => batchTagDocuments(documentIds, [nextTagId]),
    onSuccess: () => {
      setTagId("");
      invalidate();
    }
  });

  const createMutation = useMutation({
    mutationFn: () => createTag({ name: newTagName.trim(), color: "#2563eb" }),
    onSuccess: (tag) => {
      setNewTagName("");
      applyMutation.mutate(tag.id);
      invalidate();
    }
  });

  function applySelectedTag() {
    const selected = Number(tagId);
    if (!selected || !documentIds.length) return;
    applyMutation.mutate(selected);
  }

  function createAndApplyTag() {
    if (!newTagName.trim() || !documentIds.length) return;
    createMutation.mutate();
  }

  return (
    <div className={compact ? "flex flex-wrap items-center gap-2" : "space-y-3 rounded-lg border border-slate-200 bg-white p-3"}>
      {!compact ? (
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <TagIcon className="h-4 w-4" />
          文档标签
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={tagId}
          onChange={(event) => setTagId(event.target.value)}
          className="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="">选择已有标签</option>
          {(tagsQuery.data ?? []).map((tag) => (
            <option key={tag.id} value={tag.id}>{tag.name}</option>
          ))}
        </select>
        <Button type="button" size="sm" variant="outline" disabled={!tagId || !documentIds.length || applyMutation.isPending} onClick={applySelectedTag}>
          应用
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={newTagName}
          onChange={(event) => setNewTagName(event.target.value)}
          placeholder="新建标签并应用"
          className="h-9 rounded-md border border-slate-300 px-3 text-sm"
        />
        <Button type="button" size="sm" disabled={!newTagName.trim() || !documentIds.length || createMutation.isPending} onClick={createAndApplyTag}>
          <Plus className="h-4 w-4" />
          新建
        </Button>
      </div>
    </div>
  );
}
