import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { CompositionEvent, KeyboardEvent, useMemo, useState } from "react";
import { createTag, getTags } from "@/lib/api";

type TagInputProps = {
  value: string[];
  onChange: (tags: string[]) => void;
};

export function TagInput({ value, onChange }: TagInputProps) {
  const queryClient = useQueryClient();
  const tagsQuery = useQuery({ queryKey: ["tags"], queryFn: getTags });
  const [input, setInput] = useState("");
  const [isComposing, setIsComposing] = useState(false);
  const tagMode = !isComposing && input.startsWith("#");
  const needle = tagMode ? input.slice(1).trim().toLowerCase() : "";
  const existingNames = new Set(value.map((tag) => tag.toLowerCase()));
  const suggestions = useMemo(
    () => (tagsQuery.data ?? [])
      .filter((tag) => !existingNames.has(tag.name.toLowerCase()))
      .filter((tag) => tag.name.toLowerCase().includes(needle))
      .slice(0, 6),
    [existingNames, needle, tagsQuery.data]
  );

  const createMutation = useMutation({
    mutationFn: (name: string) => createTag({ name, color: "#2563eb" }),
    onSuccess: (tag) => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      addTag(tag.name);
    }
  });

  function addTag(name: string) {
    const normalized = name.trim().replace(/^#/, "");
    if (!normalized || existingNames.has(normalized.toLowerCase())) {
      setInput("");
      return;
    }
    onChange([...value, normalized]);
    setInput("");
  }

  function removeTag(name: string) {
    onChange(value.filter((tag) => tag !== name));
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (isComposing) return;
    if (event.key === "Enter" && tagMode) {
      event.preventDefault();
      if (suggestions[0]) {
        addTag(suggestions[0].name);
        return;
      }
      if (needle) {
        createMutation.mutate(needle);
      }
    }
    if (event.key === "Backspace" && !input && value.length) {
      onChange(value.slice(0, -1));
    }
  }

  function onCompositionStart(_: CompositionEvent<HTMLInputElement>) {
    setIsComposing(true);
  }

  function onCompositionEnd(_: CompositionEvent<HTMLInputElement>) {
    setIsComposing(false);
  }

  return (
    <div className="relative">
      <div className="flex min-h-10 flex-wrap items-center gap-2 rounded-md border border-slate-300 bg-white px-2 py-1.5">
        {value.map((tag) => (
          <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
            #{tag}
            <button type="button" onClick={() => removeTag(tag)} className="text-slate-400 hover:text-slate-700" aria-label={`删除标签 ${tag}`}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onKeyDown}
          onCompositionStart={onCompositionStart}
          onCompositionEnd={onCompositionEnd}
          className="min-w-36 flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none"
          placeholder={value.length ? "输入 # 添加标签" : "手动输入 # 后添加标签"}
        />
      </div>
      {tagMode ? (
        <div className="absolute left-0 right-0 top-12 z-20 rounded-2xl border border-slate-100 bg-white p-2 shadow-lg">
          {suggestions.map((tag) => (
            <button
              key={tag.id}
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => addTag(tag.name)}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-slate-50"
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: tag.color ?? "#2563eb" }} />
              #{tag.name}
            </button>
          ))}
          {needle && !suggestions.some((tag) => tag.name.toLowerCase() === needle) ? (
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => createMutation.mutate(needle)}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm text-blue-700 hover:bg-blue-50"
            >
              <Plus className="h-4 w-4" />
              创建标签：#{needle}
            </button>
          ) : null}
          {!needle && !suggestions.length ? (
            <p className="px-3 py-2 text-sm text-slate-500">暂无可选标签，继续输入名称后可创建。</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
