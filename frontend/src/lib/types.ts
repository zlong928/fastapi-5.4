export type TaskStatus = "queued" | "processing" | "success" | "failed" | string;

export interface TaskRecord {
  task_id: string;
  filename?: string;
  file_name?: string;
  file_size?: number;
  file_type?: string;
  status: TaskStatus;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
  result_path?: string | null;
  storage_path?: string;
  result?: unknown;
}

export interface UploadResponse {
  task_id: string;
  filename?: string;
  file_name?: string;
  status?: TaskStatus;
  tasks?: TaskRecord[];
  queue_size?: number;
}

export interface HealthResponse {
  status: string;
  queued_tasks?: number;
  tracked_tasks?: number;
}

export interface TaskResultResponse {
  task: TaskRecord;
  result: unknown;
}

export interface UserRead {
  id: number;
  email: string;
  username: string;
  created_at: string;
}

export interface RegisterRequest {
  email: string;
  username: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface PasswordForgotRequest {
  email: string;
}

export interface PasswordResetRequest {
  email: string;
  code: string;
  new_password: string;
}

export interface MessageResponse {
  message: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}
