import { Send, Loader2, FileText } from "lucide-react";
import { FormEvent, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { streamChat } from "@/lib/api";
import { ChatStreamSource } from "@/lib/types";

export function ChatPage() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<ChatStreamSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isStreaming) return;

    setAnswer("");
    setSources([]);
    setError(null);
    setIsStreaming(true);

    try {
      await streamChat(trimmed, {
        onSources: setSources,
        onToken: (token) => setAnswer((current) => current + token),
        onError: setError,
        onDone: () => setIsStreaming(false)
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Chat stream failed.");
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Ask your knowledge base</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">AI Chat</h1>
        <p className="mt-2 text-sm text-slate-500">
          Ask questions against parsed document chunks. Answers stream back over HTTP with source references.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block text-sm font-medium text-slate-700" htmlFor="chat-question">
            Question
          </label>
          <textarea
            id="chat-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="例如：根据我的资料，总结这个项目目前还缺什么？"
            rows={4}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-slate-500">Uses the existing chunk search as retrieval context, then streams a RAG-style answer.</p>
            <Button type="submit" disabled={isStreaming || !question.trim()} className="gap-2">
              {isStreaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {isStreaming ? "Generating" : "Ask"}
            </Button>
          </div>
        </form>
      </section>

      {(answer || isStreaming || error) && (
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Answer</h2>
            {isStreaming ? <span className="text-xs text-blue-600">Streaming...</span> : null}
          </div>
          {error ? <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-700">{error}</p> : null}
          <div className="prose prose-slate max-w-none text-sm">
            {answer ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown> : <p className="text-slate-500">Waiting for response...</p>}
          </div>
        </section>
      )}

      {sources.length > 0 && (
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold">Sources</h2>
          <div className="space-y-3">
            {sources.map((source, index) => (
              <article key={`${source.document_id}-${source.chunk_id}-${index}`} className="rounded-md border border-slate-100 bg-slate-50 p-3">
                <div className="flex items-start gap-2">
                  <FileText className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-500" />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-slate-900">
                      [{index + 1}] {source.document_title || source.filename || "Untitled document"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Chunk {source.chunk_index ?? "-"} · Score {Number(source.score ?? 0).toFixed(3)}
                      {source.page_start ? ` · Page ${source.page_start}` : ""}
                    </p>
                  </div>
                </div>
                <p className="mt-3 line-clamp-5 whitespace-pre-wrap text-sm text-slate-600">{source.text}</p>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
