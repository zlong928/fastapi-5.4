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
    title: "未命名",
    body: "",
    tags: [],
    documentTitle,
    updatedAt: new Date().toISOString()
  };
}

function statusCopy(status: SaveStatus) {
  if (status === "dirty") return "未保存";
  if (status === "saving") return "保存中";
  if (status === "failed") return "失败";
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
    if (saveStatus === "dirty" && !confirm("放弃未保存修改？")) return;
    const note = emptyNote(linkedDocumentQuery.data?.title);
    setDraft(note);
    setActiveId(note.id);
    setSaveStatus("dirty");
  }

  function selectNote(noteId: string) {
    if (noteId === activeId) return;
    if (saveStatus === "dirty" && !confirm("放弃未保存修改？")) return;
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
    <div className="mx-auto grid min-h-[calc(100vh-6rem)] max-w-7xl gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="rounded-3xl border border-slate-100 bg-white p-3">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold tracking-tight">笔记</h1>
          <Button type="button" size="sm" variant="ghost" className="h-9 w-9 rounded-xl p-0" onClick={createNote}>
            <Plus className="h-4 w-4" />
          </Button>
        </div>

        <label className="relative block">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索"
            className="h-10 w-full rounded-2xl border border-transparent bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-slate-200 focus:bg-white"
          />
        </label>

        <div className="mt-3 space-y-1.5">
          {filteredNotes.map((note) => (
            <button
              key={note.id}
              type="button"
              onClick={() => selectNote(note.id)}
              className={`w-full rounded-2xl px-3 py-2.5 text-left transition ${note.id === draft?.id ? "bg-slate-950 text-white" : "text-slate-700 hover:bg-slate-50"}`}
            >
              <p className="truncate text-sm font-medium">{note.title || "未命名"}</p>
              <p className={`mt-1 line-clamp-2 text-xs ${note.id === draft?.id ? "text-slate-300" : "text-slate-400"}`}>{note.body || "空"}</p>
            </button>
          ))}
          {!filteredNotes.length ? <p className="px-3 py-6 text-center text-sm text-slate-400">无笔记</p> : null}
        </div>
      </aside>

      {draft ? (
        <article className="rounded-3xl border border-slate-100 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <input
              value={draft.title}
              onChange={(event) => updateDraft({ title: event.target.value })}
              className="min-w-0 flex-1 border-0 bg-transparent text-2xl font-semibold tracking-tight outline-none"
              placeholder="未命名"
            />
            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs ${
                saveStatus === "dirty" ? "bg-amber-50 text-amber-700" :
                saveStatus === "failed" ? "bg-red-50 text-red-700" :
                "bg-emerald-50 text-emerald-700"
              }`}>
                {saveStatus === "failed" ? <AlertCircle className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
                {statusCopy(saveStatus)}
              </span>
              <Button type="button" variant="outline" size="sm" className="rounded-xl border-slate-100 shadow-none" onClick={saveDraft} disabled={saveStatus === "saving" || saveStatus === "saved"}>
                <Save className="h-4 w-4" />
                保存
              </Button>
            </div>
          </div>

          <div className="mt-3 flex flex-col gap-2 md:flex-row">
            <div className="min-w-0 flex-1">
              <TagInput value={draft.tags} onChange={(tags) => updateDraft({ tags })} />
            </div>
            <input
              value={draft.documentTitle ?? ""}
              onChange={(event) => updateDraft({ documentTitle: event.target.value })}
              className="h-10 rounded-2xl border border-slate-100 bg-white px-3 text-sm outline-none focus:border-slate-200 md:w-64"
              placeholder="关联文档"
            />
          </div>

          {linkedDocumentQuery.data ? (
            <div className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 text-sm text-slate-500">
              {linkedDocumentQuery.data.title}
            </div>
          ) : null}

          <textarea
            value={draft.body}
            onChange={(event) => updateDraft({ body: event.target.value })}
            className="mt-4 min-h-[560px] w-full resize-y rounded-2xl border border-transparent bg-slate-50 p-4 text-sm leading-7 outline-none focus:border-slate-200 focus:bg-white"
            placeholder="开始写..."
          />
        </article>
      ) : (
        <div className="flex items-center justify-center rounded-3xl border border-dashed border-slate-100 bg-white text-center">
          <div>
            <FileText className="mx-auto h-8 w-8 text-slate-300" />
            <Button type="button" onClick={createNote} className="mt-4 rounded-xl">新建</Button>
          </div>
        </div>
      )}
    </div>
  );
}
