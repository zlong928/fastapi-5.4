import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Check, FileText, Plus, Save, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TagInput } from "@/components/TagInput";
import { Button } from "@/components/ui/button";
import { getDocument } from "@/lib/api";

type SaveStatus = "saved" | "dirty" | "saving" | "failed";

type Note = {
  id: string;
  title: string;
  body: string;
  tags: string[];
  documentTitle?: string;
  updatedAt: string;
};

const STORAGE_KEY = "second_brain_notes";

function loadNotes(): Note[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) as Note[] : [];
  } catch {
    return [];
  }
}

function saveNotes(notes: Note[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(notes));
}

function emptyNote(documentTitle?: string): Note {
  return {
    id: crypto.randomUUID(),
    title: "未命名笔记",
    body: "",
    tags: [],
    documentTitle,
    updatedAt: new Date().toISOString()
  };
}

function statusCopy(status: SaveStatus) {
  if (status === "dirty") return "未保存";
  if (status === "saving") return "正在保存";
  if (status === "failed") return "保存失败";
  return "已保存";
}

export function NotesPage() {
  const [searchParams] = useSearchParams();
  const linkedDocumentId = Number(searchParams.get("documentId") ?? 0);
  const linkedDocumentQuery = useQuery({
    queryKey: ["document", linkedDocumentId, "note-link"],
    queryFn: () => getDocument(linkedDocumentId),
    enabled: linkedDocumentId > 0
  });
  const [notes, setNotes] = useState<Note[]>(() => loadNotes());
  const [activeId, setActiveId] = useState(notes[0]?.id ?? "");
  const savedActive = notes.find((note) => note.id === activeId) ?? null;
  const [draft, setDraft] = useState<Note | null>(savedActive);
  const [query, setQuery] = useState("");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>(savedActive ? "saved" : "dirty");

  useEffect(() => {
    setDraft(savedActive);
    setSaveStatus(savedActive ? "saved" : "dirty");
  }, [savedActive?.id]);

  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (saveStatus !== "dirty") return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [saveStatus]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveDraft();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const filteredNotes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return notes;
    return notes.filter((note) =>
      note.title.toLowerCase().includes(needle) ||
      note.body.toLowerCase().includes(needle) ||
      note.tags.some((tag) => tag.toLowerCase().includes(needle))
    );
  }, [notes, query]);

  function createNote() {
    if (saveStatus === "dirty" && !confirm("当前笔记还未保存，是否放弃这些修改？")) return;
    const note = emptyNote(linkedDocumentQuery.data?.title);
    setDraft(note);
    setActiveId(note.id);
    setSaveStatus("dirty");
  }

  function selectNote(noteId: string) {
    if (noteId === activeId) return;
    if (saveStatus === "dirty" && !confirm("当前笔记还未保存，是否放弃这些修改？")) return;
    setActiveId(noteId);
  }

  function updateDraft(patch: Partial<Note>) {
    if (!draft) return;
    setDraft({ ...draft, ...patch });
    setSaveStatus("dirty");
  }

  function saveDraft() {
    if (!draft || saveStatus === "saving") return;
    setSaveStatus("saving");
    try {
      const nextDraft = { ...draft, updatedAt: new Date().toISOString() };
      const exists = notes.some((note) => note.id === nextDraft.id);
      const nextNotes = exists
        ? notes.map((note) => note.id === nextDraft.id ? nextDraft : note)
        : [nextDraft, ...notes];
      saveNotes(nextNotes);
      setNotes(nextNotes);
      setDraft(nextDraft);
      setSaveStatus("saved");
    } catch {
      setSaveStatus("failed");
    }
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Notes</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">笔记</h1>
          <p className="mt-2 text-sm text-slate-500">写作、整理想法并关联知识库资料。保存由你手动触发：Command + S 或 Ctrl + S。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={saveDraft} disabled={!draft || saveStatus === "saving" || saveStatus === "saved"} className="gap-2 rounded-full">
            <Save className="h-4 w-4" />
            保存
          </Button>
          <Button type="button" onClick={createNote} className="gap-2 rounded-full">
            <Plus className="h-4 w-4" />
            新建笔记
          </Button>
        </div>
      </section>

      {linkedDocumentQuery.data ? (
        <div className="rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          当前可创建关联笔记：{linkedDocumentQuery.data.title}
        </div>
      ) : null}

      <section className="grid min-h-[680px] gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="rounded-2xl border border-slate-100 bg-white p-3 shadow-sm">
          <label className="relative block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="按关键词或标签筛选笔记"
              className="h-10 w-full rounded-full border border-slate-200 pl-9 pr-3 text-sm outline-none focus:border-slate-400"
            />
          </label>
          <div className="mt-3 space-y-2">
            {filteredNotes.map((note) => (
              <button
                key={note.id}
                type="button"
                onClick={() => selectNote(note.id)}
                className={`w-full rounded-xl p-3 text-left transition ${note.id === draft?.id ? "bg-slate-950 text-white" : "bg-slate-50 text-slate-700 hover:bg-slate-100"}`}
              >
                <p className="truncate text-sm font-semibold">{note.title || "未命名笔记"}</p>
                <p className={`mt-1 line-clamp-2 text-xs ${note.id === draft?.id ? "text-slate-300" : "text-slate-500"}`}>{note.body || "空笔记"}</p>
              </button>
            ))}
            {!filteredNotes.length ? <p className="p-5 text-center text-sm text-slate-500">还没有匹配的笔记。</p> : null}
          </div>
        </aside>

        {draft ? (
          <article className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4">
              <input
                value={draft.title}
                onChange={(event) => updateDraft({ title: event.target.value })}
                className="min-w-0 flex-1 rounded-md border-0 text-2xl font-semibold tracking-tight outline-none"
                placeholder="笔记标题"
              />
              <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${
                saveStatus === "dirty" ? "bg-amber-50 text-amber-700" :
                saveStatus === "failed" ? "bg-red-50 text-red-700" :
                "bg-emerald-50 text-emerald-700"
              }`}>
                {saveStatus === "failed" ? <AlertCircle className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
                {statusCopy(saveStatus)}
              </span>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <label>
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tags</span>
                <div className="mt-1">
                  <TagInput value={draft.tags} onChange={(tags) => updateDraft({ tags })} />
                </div>
              </label>
              <label>
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">关联文档</span>
                <input
                  value={draft.documentTitle ?? ""}
                  onChange={(event) => updateDraft({ documentTitle: event.target.value })}
                  className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                  placeholder="可填写知识库文档标题"
                />
              </label>
            </div>
            <textarea
              value={draft.body}
              onChange={(event) => updateDraft({ body: event.target.value })}
              className="mt-5 min-h-[480px] w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-7 outline-none focus:border-slate-400 focus:bg-white"
              placeholder="写下你的摘要、想法、问题或下一步行动..."
            />
          </article>
        ) : (
          <div className="flex min-h-[520px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 text-center">
            <FileText className="h-10 w-10 text-slate-300" />
            <p className="mt-3 font-medium text-slate-700">开始写第一条笔记</p>
            <Button type="button" onClick={createNote} className="mt-4">新建笔记</Button>
          </div>
        )}
      </section>
    </div>
  );
}
