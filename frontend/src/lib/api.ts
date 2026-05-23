import {
  BatchDeleteResponse,
  BatchTagResponse,
  BookProgressRead,
  BookProgressUpdate,
  BookRead,
  BookUploadResponse,
  BookmarkCreate,
  BookmarkCreateResponse,
  ChatStreamSource,
  ChunkSearchResponse,
  CollectionCreate,
  CollectionRead,
  DashboardStatsResponse,
  DocumentBatchUploadItem,
  DocumentChunk,
  DocumentKgResponse,
  DocumentListParams,
  DocumentListResponse,
  DocumentProcessingMode,
  DocumentProcessingStatusResponse,
  DocumentRead,
  DocumentSearchResponse,
  DocumentUploadResponse,
  HealthResponse,
  LoginRequest,
  MessageResponse,
  PaginatedTasksResponse,
  PaginatedDocumentEvents,
  PasswordForgotRequest,
  PasswordResetRequest,
  RegisterRequest,
  StreamChatCallbacks,
  StreamChatOptions,
  TagCreate,
  TagRead,
  TagUpdate,
  TaskListParams,
  TaskRecord,
  TaskResultResponse,
  TokenResponse,
  UserRead
} from "./types";

const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const isLocalApiBaseUrl = (url: string) => /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(url);

if (import.meta.env.PROD && !rawApiBaseUrl) {
  throw new Error("Missing VITE_API_BASE_URL in production.");
}

if (import.meta.env.PROD && rawApiBaseUrl && isLocalApiBaseUrl(rawApiBaseUrl)) {
  throw new Error("VITE_API_BASE_URL must not point to localhost in production.");
}

export const API_BASE_URL = (rawApiBaseUrl || "http://localhost:8000").replace(/\/+$/, "");
const TOKEN_KEY = "file_processing_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      message = response.statusText || message;
    }
    if (response.status === 401) {
      clearToken();
      if (!window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/register") && !window.location.pathname.startsWith("/forgot-password") && !window.location.pathname.startsWith("/reset-password")) {
        window.location.assign("/login");
      }
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

function authHeaders() {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

function messageFromErrorPayload(payload: unknown, fallback: string) {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function handleUnauthorized() {
  clearToken();
  if (!window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/register") && !window.location.pathname.startsWith("/forgot-password") && !window.location.pathname.startsWith("/reset-password")) {
    window.location.assign("/login");
  }
}

function uploadForm<T>(path: string, formData: FormData, onProgress?: (progress: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    authHeaders().forEach((value, key) => xhr.setRequestHeader(key, value));

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(Math.min(99, Math.round((event.loaded / event.total) * 100)));
    };
    xhr.onload = () => {
      let payload: unknown = null;
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        payload = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        resolve(payload as T);
        return;
      }
      if (xhr.status === 401) handleUnauthorized();
      reject(new Error(messageFromErrorPayload(payload, xhr.statusText || `Request failed with ${xhr.status}`)));
    };
    xhr.onerror = () => reject(new Error("Upload failed. Please check your connection and try again."));
    xhr.send(formData);
  });
}

function parseSseMessage(rawEvent: string): { event?: string; data: unknown } | null {
  if (!rawEvent.trim()) return null;
  const lines = rawEvent.split("\n");
  const event = lines.find((line) => line.startsWith("event:"))?.slice("event:".length).trim();
  const rawData = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice("data:".length).trimStart()).join("\n");
  if (!rawData) return { event, data: "" };
  try {
    return { event, data: JSON.parse(rawData) };
  } catch {
    return { event, data: rawData };
  }
}

export function healthCheck() { return request<HealthResponse>("/health"); }
export function register(payload: RegisterRequest) { return request<UserRead>("/auth/register", { method: "POST", body: JSON.stringify(payload) }); }
export async function login(payload: LoginRequest) { const response = await request<TokenResponse>("/auth/login", { method: "POST", body: JSON.stringify(payload) }); setToken(response.access_token); return response; }
export function forgotPassword(payload: PasswordForgotRequest) { return request<MessageResponse>("/auth/password/forgot", { method: "POST", body: JSON.stringify(payload) }); }
export function resetPassword(payload: PasswordResetRequest) { return request<MessageResponse>("/auth/password/reset", { method: "POST", body: JSON.stringify(payload) }); }
export function getCurrentUser() { return request<UserRead>("/users/me"); }
export function logout() { clearToken(); }

export function searchTasks(params: TaskListParams = {}): Promise<PaginatedTasksResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== "") searchParams.set(key, String(value)); });
  const query = searchParams.toString();
  return request<PaginatedTasksResponse>(`/tasks/search${query ? `?${query}` : ""}`);
}

export function clearTasks() { return request<MessageResponse>("/tasks", { method: "DELETE" }); }
export async function getTask(taskId: string): Promise<TaskRecord> {
  const task = await request<TaskRecord>(`/tasks/${encodeURIComponent(taskId)}`);
  if (task.task_kind === "basic_file_processing" && (task.status === "success" || task.status === "succeeded" || task.status === "failed")) {
    try {
      const resultResponse = await request<TaskResultResponse>(`/tasks/${encodeURIComponent(taskId)}/result`);
      return { ...resultResponse.task, result: resultResponse.result };
    } catch {
      return task;
    }
  }
  return task;
}

export async function uploadDocument(file: File, title?: string, processingMode: DocumentProcessingMode = "auto", onProgress?: (progress: number) => void): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("processing_mode", processingMode);
  if (title) formData.append("title", title);
  return uploadForm<DocumentUploadResponse>("/documents/upload", formData, onProgress);
}

export async function batchUploadDocuments(files: File[], processingMode: DocumentProcessingMode = "auto"): Promise<DocumentBatchUploadItem[]> {
  const formData = new FormData();
  formData.append("processing_mode", processingMode);
  files.forEach((file) => formData.append("files", file));
  return request<DocumentBatchUploadItem[]>("/documents/batch-upload", { method: "POST", body: formData });
}

export function createBookmark(payload: BookmarkCreate): Promise<BookmarkCreateResponse> {
  return request<BookmarkCreateResponse>("/documents/bookmarks", { method: "POST", body: JSON.stringify(payload) });
}

export function getDocuments(params: DocumentListParams = {}): Promise<DocumentListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== "") searchParams.set(key, String(value)); });
  const query = searchParams.toString();
  return request<DocumentListResponse>(`/documents${query ? `?${query}` : ""}`);
}

export function getDocument(documentId: number): Promise<DocumentRead> { return request<DocumentRead>(`/documents/${documentId}`); }
export function getDocumentProcessingStatus(documentId: number): Promise<DocumentProcessingStatusResponse> { return request<DocumentProcessingStatusResponse>(`/documents/${documentId}/process/status`); }

export async function getDocumentFileBlob(documentId: number): Promise<Blob> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/file`, { headers });
  if (!response.ok) throw new Error(response.statusText || `Request failed with ${response.status}`);
  return response.blob();
}

export async function getDocumentFileText(documentId: number): Promise<string> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/file`, { headers });
  if (!response.ok) throw new Error(response.statusText || `Request failed with ${response.status}`);
  return response.text();
}

export function searchDocuments(query: string, limit: number = 20, mode: "keyword" | "hybrid" = "keyword", includeUnparsed = false): Promise<DocumentSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit), mode, include_unparsed: String(includeUnparsed) });
  return request<DocumentSearchResponse>(`/documents/search?${params.toString()}`);
}

export function getDocumentKg(documentId: number): Promise<DocumentKgResponse> { return request<DocumentKgResponse>(`/documents/${documentId}/kg`); }
export function searchDocumentChunks(query: string, limit: number = 20, documentId?: number, threshold: number = 0.0): Promise<ChunkSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit), threshold: String(threshold) });
  if (documentId !== undefined) params.set("document_id", String(documentId));
  return request<ChunkSearchResponse>(`/documents/search/chunks?${params.toString()}`);
}
export function reEmbedDocument(documentId: number): Promise<{ document_id: number; chunks_embedded: number; message: string }> { return request<{ document_id: number; chunks_embedded: number; message: string }>(`/documents/${documentId}/re-embed`, { method: "POST" }); }
export function reEmbedAllDocuments(): Promise<{ user_id: number; documents_processed: number; chunks_embedded: number }> { return request<{ user_id: number; documents_processed: number; chunks_embedded: number }>("/documents/re-embed-all", { method: "POST" }); }
export function getDocumentChunks(documentId: number): Promise<DocumentChunk[]> { return request<DocumentChunk[]>(`/documents/${documentId}/chunks`); }
export function retryDocumentParse(documentId: number): Promise<DocumentRead> { return request<DocumentRead>(`/documents/${documentId}/retry`, { method: "POST" }); }
export function deleteDocument(documentId: number): Promise<MessageResponse> { return request<MessageResponse>(`/documents/${documentId}`, { method: "DELETE" }); }
export function updateDocument(documentId: number, payload: { title?: string; collection_name?: string | null }): Promise<DocumentRead> { return request<DocumentRead>(`/documents/${documentId}`, { method: "PATCH", body: JSON.stringify(payload) }); }
export function batchDeleteDocuments(ids: number[]): Promise<BatchDeleteResponse> { return request<BatchDeleteResponse>("/documents/batch", { method: "DELETE", body: JSON.stringify({ ids }) }); }
export function batchTagDocuments(documentIds: number[], tagIds: number[]): Promise<BatchTagResponse> { return request<BatchTagResponse>("/documents/batch-tag", { method: "POST", body: JSON.stringify({ document_ids: documentIds, tag_ids: tagIds }) }); }
export function getDocumentEvents(documentId: number, page = 1, size = 20): Promise<PaginatedDocumentEvents> { return request<PaginatedDocumentEvents>(`/documents/${documentId}/events?page=${page}&size=${size}`); }

export async function streamChat(question: string, callbacks: StreamChatCallbacks, options: StreamChatOptions = {}) {
  const token = getToken();
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ question, top_k: options.topK ?? 5, document_id: options.documentId, threshold: options.threshold ?? 0 })
  });
  if (response.status === 401) handleUnauthorized();
  if (!response.ok || !response.body) throw new Error(response.statusText || `Request failed with ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const messages = buffer.split("\n\n");
    buffer = messages.pop() ?? "";
    for (const message of messages) {
      const parsed = parseSseMessage(message);
      if (!parsed) continue;
      if (parsed.event === "sources") callbacks.onSources?.(parsed.data as ChatStreamSource[]);
      if (parsed.event === "token") callbacks.onToken?.(String(parsed.data));
      if (parsed.event === "error") callbacks.onError?.(String(parsed.data));
      if (parsed.event === "done") callbacks.onDone?.();
    }
  }
}

export function getTags(): Promise<TagRead[]> { return request<TagRead[]>("/tags"); }
export function createTag(payload: TagCreate): Promise<TagRead> { return request<TagRead>("/tags", { method: "POST", body: JSON.stringify(payload) }); }
export function updateTag(tagId: number, payload: TagUpdate): Promise<TagRead> { return request<TagRead>(`/tags/${tagId}`, { method: "PATCH", body: JSON.stringify(payload) }); }
export function deleteTag(tagId: number): Promise<MessageResponse> { return request<MessageResponse>(`/tags/${tagId}`, { method: "DELETE" }); }
export function getCollections(): Promise<CollectionRead[]> { return request<CollectionRead[]>("/collections"); }
export function createCollection(payload: CollectionCreate): Promise<CollectionRead> { return request<CollectionRead>("/collections", { method: "POST", body: JSON.stringify(payload) }); }
export function getStatistics(): Promise<DashboardStatsResponse> { return request<DashboardStatsResponse>("/statistics"); }

export async function uploadBook(file: File): Promise<BookUploadResponse> { const formData = new FormData(); formData.append("file", file); return request<BookUploadResponse>("/api/books/upload", { method: "POST", body: formData }); }
export function getBooks(): Promise<BookRead[]> { return request<BookRead[]>("/api/books"); }
export function getBook(bookId: number): Promise<BookRead> { return request<BookRead>(`/api/books/${bookId}`); }
export function getBookProgress(bookId: number): Promise<BookProgressRead | null> { return request<BookProgressRead | null>(`/api/books/${bookId}/progress`); }
export function saveBookProgress(bookId: number, payload: BookProgressUpdate): Promise<BookProgressRead> { return request<BookProgressRead>(`/api/books/${bookId}/progress`, { method: "POST", body: JSON.stringify(payload) }); }
export function getBookFileUrl(bookId: number): string { return `${API_BASE_URL}/api/books/${bookId}/file`; }
