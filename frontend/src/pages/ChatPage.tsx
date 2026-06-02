import { ChevronDown, ChevronRight, FileText, Globe, History, Loader2, MessageSquare, Plus, Send, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { getChatSession, getChatSessions, streamChat } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { ChatMessageItem, ChatSessionListItem, ChatStreamSource } from "@/lib/types";

function sourceTitle(source: ChatStreamSource, index: number) {
  if (source.source_type === "web_search") {
    return `[网页-${index + 1}] ${source.document_title || "Web Result"}`;
  }
  if (source.source_type === "extraction_result") {
    return `提取结果${source.field_name ? ` · ${source.field_name}` : ""}`;
  }
  return `[知识库-${index + 1}] ${source.document_title || source.filename || "Untitled"}`;
}

function sourceBody(source: ChatStreamSource) {
  return source.evidence || source.text || source.content || "";
}

function sourceMeta(source: ChatStreamSource) {
  if (source.source_type === "web_search") {
    return source.source || "网页来源";
  }
  if (source.source_type === "extraction_result") {
    const parts = [
      source.document_title || source.filename || "PDF",
      source.extraction_job_id ? `Job #${source.extraction_job_id}` : null,
      source.confidence !== undefined && source.confidence !== null ? `confidence ${Number(source.confidence).toFixed(2)}` : null
    ].filter(Boolean);
    return parts.join(" · ");
  }
  return [
    source.chunk_index !== null && source.chunk_index !== undefined ? `#${source.chunk_index}` : null,
    Number.isFinite(Number(source.score)) ? Number(source.score ?? 0).toFixed(3) : null,
    source.page_start ? `p.${source.page_start}` : null
  ].filter(Boolean).join(" · ");
}

function SourceList({ sources }: { sources: ChatStreamSource[] }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (sources.length === 0) return null;

  return (
    <div className="mt-4">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-sm font-medium text-slate-700 transition-all hover:bg-slate-100 hover:shadow-sm"
      >
        {isExpanded ? <ChevronDown className="h-4 w-4 transition-transform" /> : <ChevronRight className="h-4 w-4 transition-transform" />}
        <FileText className="h-4 w-4" />
        <span>{sources.length} 个引用来源</span>
        <span className="ml-auto text-xs text-slate-400">点击{isExpanded ? "收起" : "展开"}</span>
      </button>

      {isExpanded && (
        <div className="source-expand-enter mt-2 space-y-2">
          {sources.map((source, index) => {
            const isWebSource = source.source_type === "web_search";
            return (
              <article
                key={`${source.source_type}-${source.source_id ?? source.chunk_id ?? index}-${index}`}
                className={`group rounded-lg border p-3 shadow-sm transition-all ${
                  isWebSource
                    ? "border-green-200 bg-green-50 hover:border-green-300 hover:shadow-md"
                    : "border-slate-200 bg-white hover:border-blue-300 hover:shadow-md"
                }`}
              >
                <div className="flex items-start gap-2">
                  <div className={`rounded-md p-1.5 ${isWebSource ? "bg-green-100" : "bg-blue-50"}`}>
                    {isWebSource ? (
                      <Globe className="h-4 w-4 text-green-600" />
                    ) : (
                      <FileText className="h-4 w-4 text-blue-500" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className={`truncate text-sm font-medium ${isWebSource ? "text-green-900" : "text-slate-900"} group-hover:${isWebSource ? "text-green-700" : "text-blue-600"}`}>
                      {sourceTitle(source, index)}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-500">{sourceMeta(source)}</p>
                  </div>
                </div>
                <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-slate-600">{sourceBody(source)}</p>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1">
      <div className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]"></div>
      <div className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]"></div>
      <div className="h-2 w-2 animate-bounce rounded-full bg-slate-400"></div>
    </div>
  );
}

function MessageBubble({ message, isStreaming }: { message: ChatMessageItem; isStreaming?: boolean }) {
  const isUser = message.role === "user";
  const isEmpty = !message.content && !isStreaming;

  return (
    <div className={`message-enter flex ${isUser ? "justify-end" : "justify-start"} px-4 py-3`}>
      <div className={`flex max-w-[min(800px,85%)] gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
        {/* Avatar */}
        <div className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full ${isUser ? "bg-blue-600" : "gradient-animated bg-gradient-to-br from-purple-500 via-pink-500 to-purple-600"}`}>
          {isUser ? (
            <span className="text-sm font-semibold text-white">U</span>
          ) : (
            <Sparkles className="h-4 w-4 text-white" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 space-y-2">
          {isUser ? (
            <div className="rounded-2xl bg-blue-600 px-4 py-3 text-white shadow-sm">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {isEmpty ? (
                <div className="flex items-center gap-3 rounded-xl bg-slate-100 px-4 py-3">
                  <TypingIndicator />
                  <span className="text-sm text-slate-600">正在思考...</span>
                </div>
              ) : (
                <>
                  <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-p:leading-relaxed prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline prose-pre:bg-slate-900 prose-pre:text-slate-100 prose-code:text-sm">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                  </div>
                  {isStreaming && (
                    <div className="flex items-center gap-2 text-slate-400">
                      <div className="h-1 w-1 animate-pulse rounded-full bg-slate-400"></div>
                      <span className="text-xs">生成中...</span>
                    </div>
                  )}
                </>
              )}
              <SourceList sources={message.sources || []} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ChatPage() {
  const [question, setQuestion] = useState("");
  const [sessions, setSessions] = useState<ChatSessionListItem[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [enableWebSearch, setEnableWebSearch] = useState(false);  // 新增：网页搜索开关
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const activeSession = useMemo(() => sessions.find((session) => session.id === activeSessionId) ?? null, [sessions, activeSessionId]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [question]);

  async function refreshSessions() {
    const items = await getChatSessions();
    setSessions(items);
    return items;
  }

  async function loadSession(sessionId: number) {
    setIsLoadingSession(true);
    setError(null);
    try {
      const detail = await getChatSession(sessionId);
      setActiveSessionId(detail.id);
      setMessages(detail.messages);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载失败");
    } finally {
      setIsLoadingSession(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    getChatSessions()
      .then((items) => {
        if (cancelled) return;
        setSessions(items);
        if (items.length > 0) void loadSession(items[0].id);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function startNewSession() {
    setActiveSessionId(null);
    setMessages([]);
    setError(null);
    setQuestion("");
  }

  function updateMessage(messageId: number, updater: (message: ChatMessageItem) => ChatMessageItem) {
    setMessages((current) => current.map((message) => (message.id === messageId ? updater(message) : message)));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isStreaming) return;

    const userMessageId = -Date.now();
    const assistantMessageId = userMessageId - 1;
    const now = new Date().toISOString();
    const optimisticUser: ChatMessageItem = { id: userMessageId, role: "user", content: trimmed, created_at: now, sources: [] };
    const optimisticAssistant: ChatMessageItem = { id: assistantMessageId, role: "assistant", content: "", created_at: now, sources: [] };
    let resolvedSessionId = activeSessionId;

    setMessages((current) => [...current, optimisticUser, optimisticAssistant]);
    setQuestion("");
    setError(null);
    setIsStreaming(true);

    try {
      await streamChat(
        trimmed,
        {
          onSession: (session) => {
            resolvedSessionId = session.id;
            setActiveSessionId(session.id);
          },
          onSources: (sources) => updateMessage(assistantMessageId, (message) => ({ ...message, sources })),
          onToken: (token) => updateMessage(assistantMessageId, (message) => ({ ...message, content: message.content + token })),
          onError: setError
        },
        { sessionId: activeSessionId, enableWebSearch }  // 传递网页搜索开关
      );
      const refreshed = await refreshSessions();
      const sessionId = resolvedSessionId ?? refreshed[0]?.id ?? null;
      if (sessionId) await loadSession(sessionId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "失败");
      setMessages((current) => current.filter((message) => message.id !== assistantMessageId || message.content));
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="flex h-screen bg-slate-50">
      {/* Sidebar */}
      <aside className="flex w-64 flex-col border-r border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 p-4">
          <Button
            type="button"
            onClick={startNewSession}
            className="w-full justify-start gap-2 rounded-xl bg-gradient-to-r from-slate-900 to-slate-700 text-white shadow-md transition-all hover:shadow-lg hover:brightness-110"
          >
            <Plus className="h-4 w-4" />
            新对话
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          <div className="mb-3 flex items-center gap-2 px-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            <History className="h-3.5 w-3.5" />
            历史会话
          </div>

          <div className="space-y-1">
            {sessions.length === 0 && (
              <div className="rounded-lg bg-slate-50 px-3 py-8 text-center">
                <MessageSquare className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                <p className="text-xs text-slate-400">暂无会话记录</p>
              </div>
            )}
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => void loadSession(session.id)}
                className={`group relative w-full overflow-hidden rounded-lg px-3 py-2.5 text-left transition-all ${
                  session.id === activeSessionId
                    ? "bg-gradient-to-r from-blue-50 to-purple-50 font-medium text-slate-900 shadow-sm"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {session.id === activeSessionId && (
                  <div className="absolute left-0 top-0 h-full w-1 bg-gradient-to-b from-blue-500 to-purple-500"></div>
                )}
                <p className="truncate text-sm">{session.title}</p>
                <div className="mt-1 flex items-center gap-2 text-xs text-slate-400">
                  <span className="truncate">{formatChinaDateTime(session.updated_at)}</span>
                  <span className="flex-shrink-0">·</span>
                  <span className="flex-shrink-0">{session.message_count} 条</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="border-t border-slate-200 p-3">
          <div className="rounded-lg bg-gradient-to-br from-slate-50 to-slate-100 p-3">
            <p className="text-xs font-medium text-slate-600">💡 小提示</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              使用 Shift + Enter 可以换行
            </p>
          </div>
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="flex flex-1 flex-col">
        {/* Header */}
        <header className="border-b border-slate-200 bg-white px-6 py-4">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-slate-400" />
            <h1 className="text-lg font-semibold text-slate-900">
              {activeSession?.title || "新会话"}
            </h1>
            {isLoadingSession && (
              <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
            )}
          </div>
        </header>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <div className="flex h-full items-center justify-center p-8">
              <div className="max-w-md text-center">
                <div className="gradient-animated mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-purple-500 via-pink-500 to-purple-600 shadow-lg">
                  <Sparkles className="h-10 w-10 text-white" />
                </div>
                <h2 className="text-2xl font-bold text-slate-900">你好！我能帮你什么？</h2>
                <p className="mt-3 text-sm leading-relaxed text-slate-600">
                  我可以基于你的知识库回答问题、总结文档内容、帮助你查找信息。
                </p>
                <div className="mt-8 grid gap-3">
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-left transition-all hover:border-blue-300 hover:bg-white hover:shadow-md">
                    <p className="text-sm font-medium text-slate-700">💡 提示示例</p>
                    <p className="mt-1 text-xs text-slate-500">总结一下最近上传的文档内容</p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-left transition-all hover:border-blue-300 hover:bg-white hover:shadow-md">
                    <p className="text-sm font-medium text-slate-700">🔍 搜索示例</p>
                    <p className="mt-1 text-xs text-slate-500">查找关于机器学习的相关内容</p>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="py-4">
              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  isStreaming={isStreaming && message.role === "assistant" && message.id === messages[messages.length - 1]?.id}
                />
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Error Message */}
        {error && (
          <div className="border-t border-red-200 bg-red-50 px-6 py-3">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}

        {/* Input Area */}
        <div className="border-t border-slate-200 bg-white px-6 py-4">
          <form onSubmit={onSubmit} className="mx-auto max-w-4xl">
            {/* 网页搜索开关 */}
            <div className="mb-3 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setEnableWebSearch(!enableWebSearch)}
                className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-all ${
                  enableWebSearch
                    ? "bg-blue-50 text-blue-700 ring-1 ring-blue-200 hover:bg-blue-100"
                    : "bg-slate-50 text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Globe className={`h-4 w-4 ${enableWebSearch ? "text-blue-600" : "text-slate-400"}`} />
                <span>{enableWebSearch ? "网页搜索已启用" : "启用网页搜索"}</span>
              </button>
              {enableWebSearch && (
                <span className="text-xs text-slate-500">知识库不足时将搜索互联网</span>
              )}
            </div>

            <div className="relative flex items-end gap-2 rounded-2xl border border-slate-200 bg-white shadow-sm focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20">
              <textarea
                ref={textareaRef}
                id="chat-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    onSubmit(event as any);
                  }
                }}
                placeholder="输入消息... (Shift + Enter 换行)"
                rows={1}
                disabled={isStreaming}
                className="max-h-[200px] min-h-[52px] flex-1 resize-none bg-transparent px-4 py-3 text-sm outline-none placeholder:text-slate-400"
              />
              <Button
                type="submit"
                disabled={isStreaming || !question.trim()}
                className="m-2 h-9 w-9 flex-shrink-0 rounded-lg bg-blue-600 p-0 hover:bg-blue-700 disabled:bg-slate-300"
              >
                {isStreaming ? (
                  <Loader2 className="h-4 w-4 animate-spin text-white" />
                ) : (
                  <Send className="h-4 w-4 text-white" />
                )}
              </Button>
            </div>
            <p className="mt-2 text-center text-xs text-slate-400">
              AI 可能会出错，请核实重要信息
            </p>
          </form>
        </div>
      </main>
    </div>
  );
}
