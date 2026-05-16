import { BookProgressRead, BookProgressUpdate, BookRead, BookUploadResponse, DocumentBatchUploadItem, DocumentChunk, DocumentKgResponse, DocumentListResponse, DocumentProcessingMode, DocumentRead, DocumentSearchResponse, DocumentUploadResponse, HealthResponse, LoginRequest, MessageResponse, PasswordForgotRequest, PasswordResetRequest, RegisterRequest, TaskRecord, TaskResultResponse, TokenResponse, UploadResponse, UserRead } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
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
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers
  });

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

export function healthCheck() {
  return request<HealthResponse>("/health");
}

export function register(payload: RegisterRequest) {
  return request<UserRead>("/auth/register", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function login(payload: LoginRequest) {
  const response = await request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload)
  });
  setToken(response.access_token);
  return response;
}

export function forgotPassword(payload: PasswordForgotRequest) {
  return request<MessageResponse>("/auth/password/forgot", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function resetPassword(payload: PasswordResetRequest) {
  return request<MessageResponse>("/auth/password/reset", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getCurrentUser() {
  return request<UserRead>("/auth/me");
}

export function logout() {
  clearToken();
}

export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await request<UploadResponse>("/upload", {
    method: "POST",
    body: formData
  });
  const task = response.tasks?.[0];
  return {
    ...response,
    task_id: response.task_id ?? task?.task_id ?? "",
    filename: task?.file_name ?? file.name,
    file_name: task?.file_name ?? file.name,
    status: task?.status ?? response.status
  };
}

export function getTasks() {
  return request<TaskRecord[]>("/tasks");
}

export function clearTasks() {
  return request<MessageResponse>("/tasks", {
    method: "DELETE"
  });
}

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

// Document API functions
export async function uploadDocument(file: File, title?: string, processingMode: DocumentProcessingMode = "auto"): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("processing_mode", processingMode);
  if (title) {
    formData.append("title", title);
  }
  return request<DocumentUploadResponse>("/documents/upload", {
    method: "POST",
    body: formData
  });
}

export async function batchUploadDocuments(files: File[], processingMode: DocumentProcessingMode = "auto"): Promise<DocumentBatchUploadItem[]> {
  const formData = new FormData();
  formData.append("processing_mode", processingMode);
  files.forEach((file) => formData.append("files", file));
  return request<DocumentBatchUploadItem[]>("/documents/batch-upload", {
    method: "POST",
    body: formData
  });
}

export function getDocuments(skip: number = 0, limit: number = 20): Promise<DocumentListResponse> {
  return request<DocumentListResponse>(`/documents?skip=${skip}&limit=${limit}`);
}

export function getDocument(documentId: number): Promise<DocumentRead> {
  return request<DocumentRead>(`/documents/${documentId}`);
}

export async function getDocumentFileBlob(documentId: number): Promise<Blob> {
  const token = getToken();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/file`, {
    headers
  });

  if (!response.ok) {
    throw new Error(response.statusText || `Request failed with ${response.status}`);
  }

  return response.blob();
}

export function searchDocuments(query: string, limit: number = 20, mode: "keyword" | "hybrid" = "keyword", includeUnparsed = false): Promise<DocumentSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit), mode, include_unparsed: String(includeUnparsed) });
  return request<DocumentSearchResponse>(`/documents/search?${params.toString()}`);
}

export function getDocumentKg(documentId: number): Promise<DocumentKgResponse> {
  return request<DocumentKgResponse>(`/documents/${documentId}/kg`);
}

export function getDocumentChunks(documentId: number): Promise<DocumentChunk[]> {
  return request<DocumentChunk[]>(`/documents/${documentId}/chunks`);
}

export function retryDocumentParse(documentId: number): Promise<DocumentRead> {
  return request<DocumentRead>(`/documents/${documentId}/retry-parse`, {
    method: "POST"
  });
}

export function deleteDocument(documentId: number): Promise<MessageResponse> {
  return request<MessageResponse>(`/documents/${documentId}`, {
    method: "DELETE"
  });
}

export async function uploadBook(file: File): Promise<BookUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return request<BookUploadResponse>("/api/books/upload", {
    method: "POST",
    body: formData
  });
}

export function getBooks(): Promise<BookRead[]> {
  return request<BookRead[]>("/api/books");
}

export function getBook(bookId: number): Promise<BookRead> {
  return request<BookRead>(`/api/books/${bookId}`);
}

export function getBookProgress(bookId: number): Promise<BookProgressRead | null> {
  return request<BookProgressRead | null>(`/api/books/${bookId}/progress`);
}

export function saveBookProgress(bookId: number, payload: BookProgressUpdate): Promise<BookProgressRead> {
  return request<BookProgressRead>(`/api/books/${bookId}/progress`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getBookFileUrl(bookId: number): string {
  return `${API_BASE_URL}/api/books/${bookId}/file`;
}

export { API_BASE_URL, TOKEN_KEY };
