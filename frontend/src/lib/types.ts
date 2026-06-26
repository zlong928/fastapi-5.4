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

export type DocumentStatus = "pending" | "processing" | "done" | "completed" | "failed" | "deleted" | "uploaded" | "parsing" | "parsed" | "extracting";
export type ParseJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "skipped";
export type DocumentSourceType = "pdf" | "markdown" | "txt" | "image" | "video" | "epub" | "docx" | "bookmark" | "note" | "diary";
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
  { value: "auto", label: "Auto detect", description: "Let the system choose the best parser based on the uploaded file." },
  { value: "plain_text", label: "Plain text", description: "Use for .txt or text files." },
  { value: "pdf_text", label: "PDF text extraction", description: "Extract embedded text from PDF files. OCR fallback may be used if needed." },
  { value: "scanned_pdf_ocr", label: "Scanned PDF OCR", description: "Use OCR-first processing for scanned PDF files." },
  { value: "image_ocr", label: "Image OCR", description: "Extract text from image files." },
  { value: "markdown_notes", label: "Markdown / notes", description: "Preserve Markdown-style headings and note structure." },
  { value: "table_image_ocr", label: "Table / screenshot OCR", description: "Use OCR-oriented processing for screenshots or table images." },
  { value: "basic_file_parser", label: "Basic file parser", description: "Use the simple compatibility parser for basic splitting/extraction.", advanced: true }
];

export function processingModeLabel(mode?: DocumentProcessingMode | string | null) {
  return DOCUMENT_PROCESSING_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode ?? "Auto detect";
}

export interface BookmarkCreate {
  url: string;
  title?: string;
  collection_name?: string | null;
  tag_ids?: number[];
  processing_mode?: DocumentProcessingMode;
}

export interface BookmarkCreateResponse {
  document_id: number;
  status: DocumentStatus;
  processing_status?: DocumentStatus;
  source_type: "bookmark" | string;
  source_url?: string | null;
  message: string;
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
  document_count?: number;
}

export interface CollectionCreate {
  name: string;
  description?: string | null;
}

export interface CollectionUpdate {
  name: string;
  description?: string | null;
}

export interface NoteRead {
  id: string;
  document_id: number;
  title: string;
  body: string;
  tags: string[];
  source_type: "note" | "diary";
  document_title?: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotePayload {
  title?: string | null;
  body: string;
  tags: string[];
  source_type?: "note" | "diary";
  document_title?: string | null;
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
  source_url?: string | null;
  site_name?: string | null;
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
  page_count?: number | null;
  metadata?: Record<string, unknown>;
  evidence_counts?: Record<string, number>;
  events: DocumentEventRead[];
  tags: TagRead[];
}

export interface DocumentProcessingStatusResponse {
  document_id: number;
  status: DocumentStatus;
  processing_status?: DocumentStatus;
  error?: string | null;
  processing_error?: string | null;
  collection_name?: string | null;
  source_url?: string | null;
  site_name?: string | null;
  hash?: string | null;
  content_summary?: string | null;
  chunk_count?: number | null;
  created_at: string;
  updated_at: string;
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
  source_url?: string | null;
  site_name?: string | null;
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
  page_count?: number | null;
  asset_counts?: Record<string, number>;
  claim_count?: number;
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
  source_url?: string | null;
  site_name?: string | null;
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

export interface DocumentAsset {
  id: number;
  document_id: number;
  parse_job_id?: number | null;
  asset_type: "table" | "figure" | "page_snapshot" | "equation" | "unknown" | string;
  asset_index?: number | null;
  label?: string | null;
  caption?: string | null;
  page_number?: number | null;
  file_path?: string | null;
  mime_type?: string | null;
  ocr_text?: string | null;
  markdown?: string | null;
  text_content?: string | null;
  summary?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface DocumentClaim {
  id: number;
  document_id: number;
  claim_text: string;
  claim_type: string;
  source_type: "chunk" | "table" | "figure" | string;
  source_id?: number | null;
  page_number?: number | null;
  evidence_text: string;
  confidence: string;
  metadata: Record<string, unknown>;
  created_at: string;
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
  collection_name?: string;
  file_type?: DocumentSourceType | "";
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

export interface ChatStreamSource {
  source_type?: "document_chunk" | "extraction_result" | string;
  source_id?: number | null;
  chunk_id: number | null;
  document_id: number | null;
  document_title: string | null;
  filename: string | null;
  chunk_index: number | null;
  chunk_type: string | null;
  score: number;
  text: string;
  source?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  extraction_job_id?: number | null;
  field_name?: string | null;
  content?: string | null;
  evidence?: string | null;
  confidence?: number | null;
}

export interface ChatMessageItem {
  id: number;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
  sources: ChatStreamSource[];
}

export interface ChatSessionListItem {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message?: string | null;
}

export interface ChatSessionDetail {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessageItem[];
}

export interface ChatStreamSession {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface StreamChatOptions {
  topK?: number;
  documentId?: number;
  threshold?: number;
  sessionId?: number | null;
  enableWebSearch?: boolean;  // 新增：是否启用网页搜索
}

export interface StreamChatCallbacks {
  onSession?: (session: ChatStreamSession) => void;
  onSources?: (sources: ChatStreamSource[]) => void;
  onToken?: (token: string) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
}

export interface PaperListItem {
  id: number;
  title: string;
  status: DocumentStatus;
  parse_error?: string | null;
  progress_label?: string;
  asset_counts?: Record<string, number>;
  uploaded_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaperFigure {
  id: number;
  paper_id: number;
  asset_type: "figure" | "page_snapshot" | string;
  image_path: string;
  image_url?: string | null;
  thumbnail_url?: string | null;
  figure_label: string;
  caption: string;
  page?: number | null;
  source?: string | null;
  evidence_type?: string | null;
  fallback: boolean;
  visual_role?: string | null;
  notes?: string | null;
  analysis_status?: string | null;
  analysis_error?: string | null;
  coordinate_preview?: CoordinatePreview | null;
  created_at: string;
}

export interface CoordinatePreview {
  image_type: string;
  status: string;
  row_count: number;
  data_quality: string;
  sample_limit: number;
  csv_url?: string | null;
  overlay_path?: string | null;
  summary_csv_path?: string | null;
  quality_audit_csv_path?: string | null;
  run_manifest_path?: string | null;
  selected_extractor?: string;
  reason?: string;
  chart_type_hint?: string;
  targets?: string[];
  semantic_columns?: string[];
  semantic_binding?: string;
  review_status?: string;
  review_notes?: string;
  extraction_method?: string;
  text_evidence_refs?: string[];
  request_id?: string;
  triggered_at?: string | null;
}

export interface CoordinatePreviewRunRequest {
  chart_type: string;
  targets: string[];
  sample_limit: number;
  force_regenerate?: boolean;
}

export interface PaperTable {
  id: number;
  paper_id: number;
  table_label: string;
  content: string;
  page?: number | null;
  parse_status?: "success" | "fallback" | "partial" | string;
  source?: string | null;
  error_message?: string | null;
  created_at: string;
}

export interface ExtractionResult {
  id: number;
  job_id: number;
  source_type: "text" | "asset" | "figure" | "table" | string;
  source_id?: number | null;
  field_name: string;
  content: string;
  evidence: string;
  confidence?: number | null;
  evidence_type?: "text" | "table" | "figure" | "chart" | "equation" | "page_region" | "unknown" | string;
  image_url?: string | null;
  thumbnail_url?: string | null;
  page?: number | null;
  bbox?: number[] | null;
  caption?: string | null;
  source?: string | null;
  figure_id?: string | null;
  notes?: string | null;
  structured_data?: string | null;
  parse_status?: "success" | "partial" | "failed" | string | null;
  extraction_mode?: "visual_analysis" | "text_extraction" | "fallback_caption_only" | "not_found" | string | null;
  created_at: string;
}

export interface ExtractionJob {
  id: number;
  paper_id: number;
  query: string;
  status: "pending" | "running" | "done" | "failed" | string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  results: ExtractionResult[];
  progress?: ExtractionJobProgress | null;
}

export interface ExtractionJobListItem {
  id: number;
  paper_id: number;
  paper_title: string;
  query: string;
  status: "pending" | "running" | "done" | "failed" | string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  result_count: number;
  progress?: ExtractionJobProgress | null;
}

export interface ExtractionJobProgress {
  phase: string;
  phase_label: string;
  status: string;
  percent: number;
  message: string;
  updated_at: string;
  figures_done: number;
  figures_total: number;
}

export interface ExtractionMetrics {
  queue_name: string;
  queue_size?: number | null;
  total_jobs: number;
  pending_jobs: number;
  running_jobs: number;
  done_jobs: number;
  failed_jobs: number;
  recent_7_days: number;
  success_rate?: number | null;
  avg_duration_seconds?: number | null;
  active_job_id?: number | null;
  active_job_status?: string | null;
  active_job_elapsed_seconds?: number | null;
  latest_finished_job_id?: number | null;
  latest_finished_status?: string | null;
  latest_finished_duration_seconds?: number | null;
  latest_finished_result_count?: number | null;
  active_figure_count: number;
  visual_max_workers: number;
  llm_max_concurrency: number;
  llm_min_request_interval_seconds: number;
}

export interface PaperDetail {
  id: number;
  user_id: number;
  title: string;
  file_path: string;
  status: DocumentStatus;
  parse_error?: string | null;
  text_content?: string | null;
  created_at: string;
  updated_at: string;
  figures: PaperFigure[];
  tables: PaperTable[];
  latest_extraction_job?: ExtractionJob | null;
}

export interface PaperAskEvidence {
  document_id: number;
  source_type: string;
  source_id: number;
  asset_type?: string | null;
  asset_id?: number | null;
  label?: string | null;
  page_number?: number | null;
  reason: string;
}

export interface PaperAskResponse {
  answer: string;
  evidence: PaperAskEvidence[];
  uncertainties: string[];
}

export interface PaperStatistics {
  total_papers: number;
  parsed_papers: number;
  failed_papers: number;
  processing_papers: number;
  total_extractions: number;
  successful_extractions: number;
  failed_extractions: number;
  total_figures: number;
  total_tables: number;
  avg_confidence?: number | null;
  recent_7_days_papers: number;
  recent_7_days_extractions: number;
}

export interface ChartTypeCatalogItem {
  image_type: string;
  label: string;
  suitable_for_csv: boolean;
  processing_chain: string;
  typical_content: string[];
  coordinate_output: string;
  binding_requirements: string[];
  requires_review: boolean;
}

export interface ChartRecipePanel {
  panel_id: string;
  y_top_px: number;
  y_bottom_px: number;
  y_axis_label: string;
  y_axis_unit: string;
}

export interface ChartRecipeCatalogItem {
  recipe_id: string;
  image_type: string;
  filename_prefixes: string[];
  caption_hints: string[];
  x_axis_label: string;
  x_axis_unit: string;
  x_axis_type: string;
  y_axis_type: string;
  axis_calibration_method: string;
  known_x_axis_calibrated: boolean;
  known_y_axis_calibrated: boolean;
  y_right_axis_type: string;
  source_path: string;
  panels: ChartRecipePanel[];
}

export interface BatchExtractionResult {
  paper_id: number;
  paper_title: string;
  job_id?: number | null;
  status: string;
  error?: string | null;
}

export interface ImageBatchExtractionJob {
  message?: string;
  job_id: number;
  total: number;
  processed: number;
  success: number;
  skipped: number;
  failed: number;
  status: string;
  queue_name?: string;
  error_message?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface StructuredFigureResult {
  id: number;
  figure_id?: string | null;
  caption?: string | null;
  image_url?: string | null;
  page?: number | null;
  evidence_type?: "text" | "table" | "figure" | "chart" | "equation" | "page_region" | "unknown" | string;
  source?: string | null;
  metric: string;
  value: string;
  evidence: string;
  confidence?: string | null;
  notes?: string | null;
  image_type?: string | null;
  review_status?: string | null;
  extraction_method?: string | null;
  data_points?: Record<string, unknown>[];
  text_evidence_refs?: string[];
  x_axis_label?: string | null;
  x_axis_unit?: string | null;
  x_axis_scale?: string | null;
  y_axis_label?: string | null;
  y_axis_unit?: string | null;
  y_axis_scale?: string | null;
  series_name?: string | null;
  csv_url?: string | null;
}

export interface StructuredTableResult {
  id: number;
  table_id?: string | null;
  structured_data?: string | null;
  parse_status?: string | null;
  page?: number | null;
  evidence_type?: "text" | "table" | "figure" | "chart" | "equation" | "page_region" | "unknown" | string;
  source?: string | null;
  metric: string;
  value: string;
  evidence: string;
  notes?: string | null;
}

export interface StructuredTextResult {
  id: number;
  metric: string;
  value: string;
  evidence: string;
  page?: number | null;
  evidence_type?: "text" | "table" | "figure" | "chart" | "equation" | "page_region" | "unknown" | string;
  source?: string | null;
  confidence?: string | null;
}

export interface StructuredExtractionResponse {
  paper_id: number;
  title: string;
  task: string;
  status: string;
  error_message?: string | null;
  summary: {
    figures_analyzed: number;
    tables_analyzed: number;
    text_items_extracted: number;
    failed_items: number;
    total_results: number;
    paper_figure_count?: number;
  };
  figure_results: StructuredFigureResult[];
  table_results: StructuredTableResult[];
  text_results: StructuredTextResult[];
  not_found: string[];
  paper_figures: PaperFigureAssetItem[];
  chart_type_stats: ChartTypeRuntimeStats[];
  created_at: string;
  updated_at: string;
}

export interface ChartTypeRuntimeStats {
  image_type: string;
  total: number;
  accepted: number;
  review_required: number;
  skipped: number;
  failed: number;
  row_count: number;
}

export interface PaperFigureAssetItem {
  id: number;
  figure_label: string;
  caption?: string | null;
  image_url?: string | null;
  page?: number | null;
  source?: string | null;
  evidence_type?: string;
  asset_type: string;
  coordinate_capable?: boolean;
  coordinate_preview?: CoordinatePreview | null;
}
