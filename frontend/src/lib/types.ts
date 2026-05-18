export type TaskStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "skipped" | "processing" | "success" | "parsed" | string;
export type TaskKind = "basic_file_processing" | "document_parse" | string;

export interface TaskRecord {
  task_id: string;
  task_kind: TaskKind;
  document_id: number | null;
  file_name: string;
  file_size: number;
  file_type: string;
  status: TaskStatus;
  progress: number;
  error: string | null;
  storage_path: string | null;
  result_path: string | null;
  created_at: string;
  updated_at: string | null;
  completed_at: string | null;
  metadata_json: string | null;
  filename?: string;
  result?: unknown;
}

export interface TaskListParams {
  page?: number;
  size?: number;
  q?: string;
  status?: string;
  kind?: string;
  document_id?: number;
  sort_by?: "created_at" | "updated_at" | "finished_at" | "file_name" | "status" | "kind" | "progress";
  sort_order?: "asc" | "desc";
}

export interface PaginatedTasksResponse {
  total: number;
  page: number;
  size: number;
  items: TaskRecord[];
}

export interface HealthResponse {
  status: string;
  queued_tasks?: number;
  tracked_tasks?: number;
  tracked_tasks_total?: number;
  basic_file_tasks_total?: number;
  parse_jobs_total?: number;
  parse_jobs_active?: number;
  parse_jobs_failed?: number;
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

export interface BookRead {
  id: number;
  title: string;
  original_filename: string;
  created_at: string;
  last_opened_at: string | null;
}

export interface BookUploadResponse {
  book_id: number;
  title: string;
  original_filename: string;
}

export interface BookProgressRead {
  id: number;
  book_id: number;
  user_id: number | null;
  location_cfi: string | null;
  progress_percent: number | null;
  updated_at: string;
}

export interface BookProgressUpdate {
  location_cfi: string;
  progress_percent?: number | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export type DocumentStatus = "pending" | "processing" | "done" | "completed" | "failed" | "deleted";
export type ParseJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "skipped";
export type DocumentSourceType = "pdf" | "markdown" | "txt" | "image";
export type DocumentProcessingMode =
  | "auto"
  | "plain_text"
  | "pdf_text"
  | "scanned_pdf_ocr"
  | "image_ocr"
  | "markdown_notes"
  | "table_image_ocr"
  | "basic_file_parser";

export const DOCUMENT_PROCESSING_MODE_OPTIONS: Array<{
  value: DocumentProcessingMode;
  label: string;
  description: string;
  advanced?: boolean;
}> = [
  {
    value: "auto",
    label: "Auto detect",
    description: "Let the system choose the best parser based on the uploaded file."
  },
  {
    value: "plain_text",
    label: "Plain text",
    description: "Use for .txt or text files."
  },
  {
    value: "pdf_text",
    label: "PDF text extraction",
    description: "Extract embedded text from PDF files. OCR fallback may be used if needed."
  },
  {
    value: "scanned_pdf_ocr",
    label: "Scanned PDF OCR",
    description: "Use OCR-first processing for scanned PDF files."
  },
  {
    value: "image_ocr",
    label: "Image OCR",
    description: "Extract text from image files."
  },
  {
    value: "markdown_notes",
    label: "Markdown / notes",
    description: "Preserve Markdown-style headings and note structure."
  },
  {
    value: "table_image_ocr",
    label: "Table / screenshot OCR",
    description: "Use OCR-oriented processing for screenshots or table images."
  },
  {
    value: "basic_file_parser",
    label: "Basic file parser",
    description: "Use the simple compatibility parser for basic splitting/extraction.",
    advanced: true
  }
];

export function processingModeLabel(mode?: DocumentProcessingMode | string | null) {
  return DOCUMENT_PROCESSING_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode ?? "Auto detect";
}

export interface DocumentEventRead {
  id: number;
  document_id: number;
  user_id: number;
  event_type: string;
  message: string;
  event_metadata?: string;
  created_at: string;
}

export interface PaginatedDocumentEvents {
  total: number;
  page: number;
  size: number;
  items: DocumentEventRead[];
}

export interface TagRead {
  id: number;
  user_id: number;
  name: string;
  color?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TagCreate {
  name: string;
  color?: string | null;
}

export interface TagUpdate {
  name?: string;
  color?: string | null;
}

export interface CollectionRead {
  id: number;
  user_id: number;
  name: string;
  description?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CollectionCreate {
  name: string;
  description?: string | null;
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
  processing_mode: DocumentProcessingMode;
  processing_strategy?: string | null;
  parsed_text?: string | null;
  cleaned_text?: string | null;
  parse_quality_json?: string | null;
  references_text?: string | null;
  status: DocumentStatus;
  processing_status?: DocumentStatus;
  error_message?: string | null;
  fail_reason?: string | null;
  processing_error?: string | null;
  created_at: string;
  updated_at: string;
  uploaded_at: string;
  parsed_at?: string | null;
  latest_parse_job?: ParseJobRead | null;
  collection_name?: string | null;
  content_hash?: string | null;
  content_summary?: string | null;
  chunk_count: number;
  events: DocumentEventRead[];
  tags: TagRead[];
}

export interface ParseJobRead {
  id: number;
  job_id?: string | null;
  document_id: number;
  user_id: number;
  status: ParseJobStatus | string;
  job_type: string;
  metadata_json?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListItem {
  id: number;
  title: string;
  original_filename: string;
  file_size: number;
  source_type: DocumentSourceType;
  processing_mode: DocumentProcessingMode;
  processing_strategy?: string | null;
  status: DocumentStatus;
  processing_status?: DocumentStatus;
  error_message?: string | null;
  fail_reason?: string | null;
  processing_error?: string | null;
  latest_parse_job_status?: ParseJobStatus | string | null;
  collection_name?: string | null;
  content_hash?: string | null;
  content_summary?: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  uploaded_at: string;
  parsed_at?: string | null;
  tags: TagRead[];
}

export interface DocumentListResponse {
  total: number;
  page: number;
  size: number;
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

export interface ChunkSearchHit {
  chunk_id: number;
  id: string;
  document_id: number;
  document_title: string;
  filename: string;
  chunk_index: number;
  chunk_type: string;
  text: string;
  score: number;
  metadata: Record<string, unknown>;
  source?: string | null;
  start_index?: number | null;
  hash?: string | null;
  page_start?: number | null;
  page_end?: number | null;
}

export interface ChunkSearchResponse {
  query: string;
  total: number;
  items: ChunkSearchHit[];
}

export interface DocumentChunk {
  id: number;
  document_id: number;
  parse_job_id?: number | null;
  chunk_index: number;
  chunk_type: string;
  text: string;
  cleaned_text: string;
  token_count?: number | null;
  char_start?: number | null;
  char_end?: number | null;
  page_start?: number | null;
  page_end?: number | null;
  metadata_json?: string | null;
  vector_id?: string | null;
  embedding_model?: string | null;
  embedding_dim?: number | null;
  embedded_at?: string | null;
  created_at: string;
  [key: string]: unknown;
}

export interface DocumentUploadResponse {
  document_id: number;
  status: DocumentStatus;
  processing_status?: DocumentStatus;
  parse_job_id: number;
  processing_mode: DocumentProcessingMode;
  message: string;
}

export interface DocumentBatchUploadItem {
  filename: string;
  ok: boolean;
  document_id?: number | null;
  parse_job_id?: number | null;
  status?: DocumentStatus | null;
  processing_mode?: DocumentProcessingMode | null;
  error?: string | null;
}

export interface DocumentListParams {
  page?: number;
  size?: number;
  keyword?: string;
  tag_id?: number;
  file_type?: "pdf" | "markdown" | "txt" | "";
  status?: DocumentStatus | "";
  start_date?: string;
  end_date?: string;
  sort_by?: "created_at" | "uploaded_at" | "parsed_at" | "title" | "file_size" | "status" | "source_type";
  sort_order?: "asc" | "desc";
}

export interface BatchDeleteResponse {
  success_ids: number[];
  failed_ids: number[];
  errors: Record<string, string>;
}

export interface BatchTagResponse {
  document_ids: number[];
  tag_ids: number[];
  assigned_count: number;
}

export interface DashboardStatsResponse {
  total_documents: number;
  done_documents: number;
  failed_documents: number;
  parse_success_rate: number;
  recent_7_days_documents: number;
  file_type_distribution: Array<{ file_type: string; count: number; ratio: number }>;
  status_distribution: Array<{ status: string; count: number }>;
}
