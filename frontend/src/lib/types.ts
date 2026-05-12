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

export type DocumentStatus = "pending" | "processing" | "parsed" | "failed" | "deleted";
export type DocumentSourceType = "pdf" | "markdown" | "txt" | "image";

export interface DocumentEventRead {
  id: number;
  document_id: number;
  user_id: number;
  event_type: string;
  message: string;
  event_metadata?: string;
  created_at: string;
}

export interface DocumentRead {
  id: number;
  user_id: number;
  title: string;
  original_filename: string;
  stored_filename: string;
  original_file_path: string;
  file_size: number;
  mime_type: string;
  source_type: DocumentSourceType;
  parsed_text?: string | null;
  cleaned_text?: string | null;
  parse_quality_json?: string | null;
  references_text?: string | null;
  status: DocumentStatus;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  uploaded_at: string;
  parsed_at?: string | null;
  events: DocumentEventRead[];
}

export interface DocumentListItem {
  id: number;
  title: string;
  original_filename: string;
  file_size: number;
  source_type: DocumentSourceType;
  status: DocumentStatus;
  created_at: string;
  uploaded_at: string;
  parsed_at?: string | null;
}

export interface DocumentListResponse {
  total: number;
  items: DocumentListItem[];
}

export interface DocumentSearchResult {
  id: number;
  title: string;
  source_type: DocumentSourceType;
  status: DocumentStatus;
  snippet: string;
  matched_field: string;
  score: number;
  parsed_at?: string | null;
}

export interface DocumentSearchResponse {
  query: string;
  total: number;
  items: DocumentSearchResult[];
}

export interface KgEntityRead {
  id: number;
  document_id: number;
  chunk_id?: number | null;
  name: string;
  entity_type: string;
  normalized_name: string;
}

export interface KgRelationRead {
  id: number;
  document_id: number;
  chunk_id: number;
  subject_text: string;
  predicate: string;
  object_text: string;
  evidence_text: string;
  confidence: number;
}

export interface DocumentKgResponse {
  document_id: number;
  entities: KgEntityRead[];
  relations: KgRelationRead[];
}

export interface DocumentUploadResponse {
  id: number;
  title: string;
  original_filename: string;
  status: DocumentStatus;
  created_at: string;
}
