import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, FileText, Plus, Save, Search, Trash2 } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TagInput } from "@/components/TagInput";
import { Button } from "@/components/ui/button";
import { API_BASE_URL, getDocument, getToken } from "@/lib/api";
import { NotePayload, NoteRead } from "@/lib/types";

type SaveStatus = "saved" | "dirty" | "saving" | "failed";
type NoteDraft = {
  id: string;
  document_id?: number;
  title: string;
  body: string;
  tags: string[];
  source_type: "note" | "diary";
  document_title?: string | null;
  created_at?: string;
  updated_at: string;
};

function statusCopy(status: SaveStatus) {
  if (status === "dirty") return "未保存";
  if (status === "saving") return "保存中";
  if (status === "failed") return "保存失败";
  return "已保存";
}

function toDraft(note: NoteRead): NoteDraft {
  return {
    id: note.id,
    document_id: note.document_id,
    title: note.title === "未命名笔记" ? "" : note.title,
    body: note.body,
    tags: note.tags,
    source_type: note.source_type,
    document_title: note.document_title,
    created_at: note.created_at,
    updated_at: note.updated_at
  };
}

function createEmptyDraft(documentTitle?: string | null): NoteDraft {
  return {
    id: crypto.randomUUID(),
    title: "",
    body: "",
    tags: [],
    source_type: "note",
    document_title: documentTitle,
    updated_at: new Date().toISOString()
  };
}

function noteLabel(note: Pick<NoteDraft, "title" | "body">) {
  return note.title.trim() || note.body.trim().slice(0, 28) || "未命名笔记";
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json", ...init?.headers });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) message = payload.detail;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function listNotes() {
  return requestJson<NoteRead[]>("/notes");
}

function saveNote(draft: NoteDraft) {
  const payload: NotePayload = {
    title: draft.title.trim() || null,
    body: draft.body,
    tags: draft.tags,
    source_type: draft.source_type,
    document_title: draft.document_title ?? null
  };
  const path = draft.document_id ? `/notes/${draft.id}` : "/notes";
  return requestJson<NoteRead>(path, { method: draft.document_id ? "PATCH" : "POST", body: JSON.stringify(payload) });
}

function deleteNote(noteId: string) {
  return requestJson<{ id: string; status: string }>(`/notes/${noteId}`, { method: "DELETE" });
}

export function NotesPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedDocumentId = Number(searchParams.get("documentId") ?? 0);
  const requestedNoteId = searchParams.get("noteId");
  const linkedDocumentQuery = useQuery({
    queryKey: ["document", linkedDocumentId, "note-link"],
    queryFn: () => getDocument(linkedDocumentId),
    enabled: linkedDocumentId > 0
  });
  const notesQuery = useQuery({ queryKey: ["notes"], queryFn: listNotes });
  const notes = notesQuery.data ?? [];
  const [activeId, setActiveId] = useState("");
  const [draft, setDraft] = useState<NoteDraft | null>(null);
  const [query, setQuery] = useState("");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("saved");

  useEffect(() => {
    if (draft || notesQuery.isLoading) return;
    const target = requestedNoteId ? notes.find((note) => note.id === requestedNoteId) : notes[0];
    if (target) {
      setDraft(toDraft(target));
      setActiveId(target.id);
      setSaveStatus("saved");
    }
  }, [draft, notes, notesQuery.isLoading, requestedNoteId]);

  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (saveStatus !== "dirty") return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [saveStatus]);

  const saveMutation = useMutation({
    mutationFn: saveNote,
    onMutate: () => setSaveStatus("saving"),
    onSuccess: (note) => {
      const nextDraft = toDraft(note);
      setDraft(nextDraft);
      setActiveId(note.id);
      setSaveStatus("saved");
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set("noteId", note.id);
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["statistics"] });
    },
    onError: () => setSaveStatus("failed")
  });
  const deleteMutation = useMutation({
    mutationFn: deleteNote,
    onSuccess: () => {
      setDraft(null);
      setActiveId("");
      setSaveStatus("saved");
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["statistics"] });
    }
  });

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (draft) saveMutation.mutate(draft);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [draft, saveMutation]);

  const filteredNotes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return notes;
    return notes.filter((note) => note.title.toLowerCase().includes(needle) || note.body.toLowerCase().includes(needle) || note.tags.some((tag) => tag.toLowerCase().includes(needle)));
  }, [notes, query]);

  function createNote() {
    if (saveStatus === "dirty" && !confirm("当前笔记还未保存，是否放弃这些修改？")) return;
    const note = createEmptyDraft(linkedDocumentQuery.data?.title ?? null);
    setDraft(note);
    setActiveId(note.id);
    setSaveStatus("dirty");
  }

  function selectNote(noteId: string) {
    if (noteId === activeId) return;
    if (saveStatus === "dirty" && !confirm("当前笔记还未保存，是否放弃这些修改？")) return;
    const target = notes.find((note) => note.id === noteId);
    if (!target) return;
    setActiveId(noteId);
    setDraft(toDraft(target));
    setSaveStatus("saved");
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("noteId", noteId);
      return next;
    });
  }

  function updateDraft(patch: Partial<NoteDraft>) {
    if (!draft) return;
    setDraft({ ...draft, ...patch, updated_at: new Date().toISOString() });
    setSaveStatus("dirty");
  }

  function submitSave(event?: FormEvent) {
    event?.preventDefault();
    if (!draft || saveStatus === "saving") return;
    if (!draft.title.trim() && !draft.body.trim() && draft.tags.length === 0) return;
    saveMutation.mutate(draft);
  }

  function confirmDelete() {
    if (!draft?.document_id) {
      setDraft(null);
      setActiveId("");
      setSaveStatus("saved");
      return;
    }
    if (!confirm(`删除笔记「${noteLabel(draft)}」？此操作不可恢复。`)) return;
    deleteMutation.mutate(draft.id);
  }

  return (
    <div className="mx-auto grid min-h-[calc(100vh-6rem)] max-w-7xl gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="rounded-3xl border border-slate-100 bg-white p-3">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold tracking-tight">笔记</h1>
          <Button type="button" size="sm" variant="ghost" className="h-9 w-9 rounded-xl p-0" onClick={createNote}><Plus className="h-4 w-4" /></Button>
        </div>
        <label className="relative block"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索笔记" className="h-10 w-full rounded-2xl border border-transparent bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-slate-200 focus:bg-white" /></label>
        <div className="mt-3 space-y-1.5">
          {draft && !draft.document_id ? <button type="button" className="w-full rounded-2xl bg-slate-950 px-3 py-2.5 text-left text-white"><p className="truncate text-sm font-medium">草稿 · {noteLabel(draft)}</p><p className="mt-1 line-clamp-2 text-xs text-slate-300">{draft.body || "尚未保存"}</p></button> : null}
          {filteredNotes.map((note) => <button key={note.id} type="button" onClick={() => selectNote(note.id)} className={`w-full rounded-2xl px-3 py-2.5 text-left transition ${note.id === activeId ? "bg-slate-950 text-white" : "text-slate-700 hover:bg-slate-50"}`}><p className="truncate text-sm font-medium">{note.title || "未命名笔记"}</p><p className={`mt-1 line-clamp-2 text-xs ${note.id === activeId ? "text-slate-300" : "text-slate-400"}`}>{note.body || "空"}</p>{note.tags.length ? <p className={`mt-1 truncate text-xs ${note.id === activeId ? "text-slate-300" : "text-slate-400"}`}>{note.tags.map((tag) => `#${tag}`).join(" ")}</p> : null}</button>)}
          {!filteredNotes.length && !draft ? <p className="px-3 py-6 text-center text-sm text-slate-400">还没有笔记，创建第一条笔记</p> : null}
        </div>
      </aside>

      {draft ? <form onSubmit={submitSave} className="rounded-3xl border border-slate-100 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><input value={draft.title} onChange={(event) => updateDraft({ title: event.target.value })} className="min-w-0 flex-1 border-0 bg-transparent text-2xl font-semibold tracking-tight outline-none" placeholder="给这篇笔记命名" /><div className="flex items-center gap-2"><span className={`inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs ${saveStatus === "dirty" ? "bg-amber-50 text-amber-700" : saveStatus === "failed" ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>{saveStatus === "failed" ? <AlertCircle className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}{statusCopy(saveStatus)}</span><Button type="submit" variant={saveStatus === "dirty" ? "default" : "outline"} size="sm" className="rounded-xl border-slate-100 shadow-none" disabled={saveStatus === "saving" || saveStatus === "saved"}><Save className="h-4 w-4" />保存</Button><Button type="button" variant="ghost" size="sm" className="rounded-xl text-red-500" onClick={confirmDelete} disabled={deleteMutation.isPending}><Trash2 className="h-4 w-4" />删除</Button></div></div><div className="mt-3 flex flex-col gap-2 md:flex-row"><div className="min-w-0 flex-1"><TagInput value={draft.tags} onChange={(tags) => updateDraft({ tags })} /></div><select value={draft.source_type} onChange={(event) => updateDraft({ source_type: event.target.value as "note" | "diary" })} className="h-10 rounded-2xl border border-slate-100 bg-white px-3 text-sm outline-none focus:border-slate-200 md:w-32"><option value="note">笔记</option><option value="diary">日记</option></select><input value={draft.document_title ?? ""} onChange={(event) => updateDraft({ document_title: event.target.value })} className="h-10 rounded-2xl border border-slate-100 bg-white px-3 text-sm outline-none focus:border-slate-200 md:w-64" placeholder="关联文档" /></div>{linkedDocumentQuery.data ? <div className="mt-3 rounded-2xl bg-slate-50 px-3 py-2 text-sm text-slate-500">关联：{linkedDocumentQuery.data.title}</div> : null}<textarea value={draft.body} onChange={(event) => updateDraft({ body: event.target.value })} className="mt-4 min-h-[560px] w-full resize-y rounded-2xl border border-transparent bg-slate-50 p-4 text-sm leading-7 outline-none focus:border-slate-200 focus:bg-white" placeholder="开始写..." /></form> : <div className="flex items-center justify-center rounded-3xl border border-dashed border-slate-100 bg-white text-center"><div><FileText className="mx-auto h-8 w-8 text-slate-300" /><p className="mt-3 text-sm text-slate-400">还没有笔记，创建第一条笔记</p><Button type="button" onClick={createNote} className="mt-4 rounded-xl">新建</Button></div></div>}
    </div>
  );
}
