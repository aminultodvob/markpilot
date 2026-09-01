/**
 * Types mirroring the converter service's API contract.
 *
 * Kept strict deliberately: `unknown` over `any`, and every optional field
 * marked optional, so a missing metadata key is a compile error rather than a
 * runtime `undefined` rendered into the UI.
 */

export type FileStatus =
  | "queued"
  | "processing"
  | "completed"
  | "failed"
  | "cancelled";

export type ConversionStage =
  | "detecting"
  | "converting"
  | "ocr"
  | "finalizing";

export type OcrMode = "auto" | "force" | "off";

/** Values the language selector offers. "auto" uses the server default. */
export type OcrLanguage = "auto" | "eng" | "ben" | "eng+ben";

export interface ApiErrorBody {
  code: string;
  message: string;
  detail?: string | null;
}

export interface ConversionMetadata {
  format: string;
  label: string;
  category: string;
  duration_ms: number;
  source_bytes: number;
  word_count: number;
  character_count: number;
  ocr_used: boolean;
  contains_raw_html: boolean;
  engine: string;
  pages?: number;
  sheets?: number;
  slides?: number;
  title?: string;
  ocr_languages?: string;
  ocr_confidence?: number;
  ocr_pages?: number;
}

export interface FileResult {
  id: string;
  filename: string;
  output_filename: string;
  size: number;
  status: FileStatus;
  stage?: ConversionStage | null;
  source_archive?: string | null;
  metadata?: ConversionMetadata | null;
  warnings: string[];
  error?: ApiErrorBody | null;
}

export interface Job {
  id: string;
  status: string;
  created_at: string;
  file_count: number;
  completed_count: number;
  files: FileResult[];
}

export interface JobCreated extends Job {
  session_id: string;
  session_token: string;
  expires_at: string;
}

export interface MarkdownResult {
  id: string;
  filename: string;
  output_filename: string;
  format: string;
  status: string;
  markdown: string;
  metadata: ConversionMetadata;
  warnings: string[];
}

export interface FormatLimits {
  max_file_size_mb: number;
  max_total_upload_mb: number;
  max_files_per_job: number;
  session_ttl_minutes: number;
}

export interface ConversionSettings {
  ocrMode: OcrMode;
  ocrLanguage: OcrLanguage;
  pageRange: string;
}

export const DEFAULT_SETTINGS: ConversionSettings = {
  ocrMode: "auto",
  ocrLanguage: "auto",
  pageRange: "",
};

/** A session credential pair. Held in memory only, never persisted. */
export interface SessionCredentials {
  sessionId: string;
  sessionToken: string;
}
