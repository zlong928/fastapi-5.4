import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { TagInput } from "@/components/TagInput";
import { batchTagDocuments, getTags } from "@/lib/api";
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
  const [draftTags, setDraftTags] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const applyMutation = useMutation({
    mutationFn: async (names: string[]) => {
      const knownTags = tagsQuery.data ?? [];
      const tagIds = names.map((name) => knownTags.find((tag) => tag.name.toLowerCase() === name.toLowerCase())?.id).filter((id): id is number => Boolean(id));
      if (!tagIds.length || !documentIds.length) return null;
      return batchTagDocuments(documentIds, tagIds);
    },
    onSuccess: () => {
      setMessage("已应用");
      setDraftTags([]);
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  });

  function onTagsChange(tags: string[]) {
    setDraftTags(tags);
    if (tags.length) applyMutation.mutate(tags);
  }

  return (
    <div className={compact ? "space-y-2" : "space-y-2 rounded-2xl border border-slate-100 bg-white p-3"}>
      <TagInput value={draftTags} onChange={onTagsChange} />
      {message ? <p className="text-xs text-emerald-600">{message}</p> : null}
    </div>
  );
}

export const DocumentTagEditor = TagSelector;
