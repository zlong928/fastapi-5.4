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
      setError(caught instanceof Error ? caught.message : "失败");
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-3xl border border-slate-100 bg-white p-4">
        <form onSubmit={onSubmit} className="space-y-3">
          <textarea
            id="chat-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="问点什么..."
            rows={4}
            className="w-full resize-none rounded-2xl border border-transparent bg-slate-50 px-4 py-3 text-sm outline-none focus:border-slate-200 focus:bg-white"
          />
          <div className="flex justify-end">
            <Button type="submit" disabled={isStreaming || !question.trim()} className="rounded-2xl bg-slate-950 px-4 text-white hover:bg-slate-800">
              {isStreaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
        </form>
      </section>

      {(answer || isStreaming || error) && (
        <section className="rounded-3xl border border-slate-100 bg-white p-4">
          {error ? <p className="mb-3 rounded-2xl bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p> : null}
          <div className="prose prose-slate max-w-none text-sm">
            {answer ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown> : <p className="text-slate-400">生成中...</p>}
          </div>
        </section>
      )}

      {sources.length > 0 && (
        <section className="space-y-2">
          {sources.map((source, index) => (
            <article key={`${source.document_id}-${source.chunk_id}-${index}`} className="rounded-2xl border border-slate-100 bg-white p-3 hover:bg-slate-50">
              <div className="flex items-start gap-2">
                <FileText className="mt-0.5 h-4 w-4 flex-shrink-0 text-slate-400" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-900">
                    [{index + 1}] {source.document_title || source.filename || "Untitled"}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    #{source.chunk_index ?? "-"} · {Number(source.score ?? 0).toFixed(3)}
                    {source.page_start ? ` · p.${source.page_start}` : ""}
                  </p>
                </div>
              </div>
              <p className="mt-3 line-clamp-5 whitespace-pre-wrap text-sm text-slate-600">{source.text}</p>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
