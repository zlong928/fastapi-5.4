import { DocumentListResponse, DocumentRead, DocumentSearchResponse, HealthResponse, LoginRequest, MessageResponse, PasswordForgotRequest, PasswordResetRequest, RegisterRequest, TaskRecord, TaskResultResponse, TokenResponse, UploadResponse, UserRead } from "./types";

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
  if (task.status === "success" || task.status === "failed") {
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
export async function uploadDocument(file: File, title?: string): Promise<any> {
  const formData = new FormData();
  formData.append("file", file);
  if (title) {
    formData.append("title", title);
  }
  return request<any>("/documents/upload", {
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

export function searchDocuments(query: string, limit: number = 20, mode: "keyword" | "hybrid" = "keyword"): Promise<DocumentSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit), mode });
  return request<DocumentSearchResponse>(`/documents/search?${params.toString()}`);
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

export { API_BASE_URL, TOKEN_KEY };
