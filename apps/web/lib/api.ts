/**
 * Client for the converter API.
 *
 * Requests go to this app's own `/api/converter/*` route, which proxies to the
 * converter service over the internal network. The converter is therefore
 * never exposed publicly, and its URL never reaches the browser.
 *
 * Session credentials live in memory for the life of the page. They are
 * deliberately not written to localStorage: a refresh starting a clean session
 * is the correct behaviour for a tool that stores nothing.
 */

import type {
  ApiErrorBody,
  ConversionSettings,
  Job,
  JobCreated,
  MarkdownResult,
  SessionCredentials,
} from "./types";

const BASE = "/api/converter";

export class ApiError extends Error {
  readonly code: string;
  readonly detail: string | null;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.detail = body.detail ?? null;
  }
}

const NETWORK_ERROR: ApiErrorBody = {
  code: "network_error",
  message: "We couldn't reach the converter. Please check your connection.",
};

function authHeaders(session: SessionCredentials): HeadersInit {
  return {
    "X-Session-Id": session.sessionId,
    "X-Session-Token": session.sessionToken,
  };
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const payload = (await response.json()) as { error?: ApiErrorBody };
    if (payload.error) return new ApiError(response.status, payload.error);
  } catch {
    // Fall through to the generic message below.
  }
  return new ApiError(response.status, {
    code: "unexpected_error",
    message: "Something went wrong. Please try again.",
  });
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, NETWORK_ERROR);
  }
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

function settingsToForm(form: FormData, settings: ConversionSettings): void {
  form.append("ocr_mode", settings.ocrMode);
  if (settings.ocrLanguage !== "auto") {
    form.append("ocr_languages", settings.ocrLanguage);
  }
  if (settings.pageRange.trim()) {
    form.append("page_range", settings.pageRange.trim());
  }
}

/** Upload files and start a conversion job. */
export async function createJob(
  files: File[],
  settings: ConversionSettings,
  signal?: AbortSignal,
): Promise<JobCreated> {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  settingsToForm(form, settings);

  return request<JobCreated>("/api/v1/jobs", {
    method: "POST",
    body: form,
    signal,
  });
}

export async function fetchJob(
  session: SessionCredentials,
  jobId: string,
  signal?: AbortSignal,
): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}`, {
    headers: authHeaders(session),
    signal,
  });
}

export async function fetchMarkdown(
  session: SessionCredentials,
  jobId: string,
  fileId: string,
): Promise<MarkdownResult> {
  return request<MarkdownResult>(`/api/v1/jobs/${jobId}/files/${fileId}`, {
    headers: authHeaders(session),
  });
}

export async function cancelJob(
  session: SessionCredentials,
  jobId: string,
): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: authHeaders(session),
  });
}

export async function retryFile(
  session: SessionCredentials,
  jobId: string,
  fileId: string,
  settings: ConversionSettings,
): Promise<Job> {
  const form = new FormData();
  settingsToForm(form, settings);
  return request<Job>(`/api/v1/jobs/${jobId}/files/${fileId}/retry`, {
    method: "POST",
    headers: authHeaders(session),
    body: form,
  });
}

export async function clearSession(session: SessionCredentials): Promise<void> {
  try {
    await fetch(`${BASE}/api/v1/sessions/${session.sessionId}`, {
      method: "DELETE",
      headers: authHeaders(session),
      // Survives the page being closed, so files are released promptly.
      keepalive: true,
    });
  } catch {
    // The session expires on the server regardless; nothing to recover here.
  }
}

/** Trigger a browser download from a blob response. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Download one result. `edited` is sent when the user changed the Markdown. */
export async function downloadFile(
  session: SessionCredentials,
  jobId: string,
  fileId: string,
  filename: string,
  edited?: string,
): Promise<void> {
  if (edited !== undefined) {
    // Edits live only in the browser, so save them without a round trip.
    saveBlob(
      new Blob([edited], { type: "text/markdown;charset=utf-8" }),
      filename,
    );
    return;
  }

  const response = await fetch(
    `${BASE}/api/v1/jobs/${jobId}/files/${fileId}/download`,
    { headers: authHeaders(session) },
  );
  if (!response.ok) throw await toApiError(response);
  saveBlob(await response.blob(), filename);
}

/** Download every result as a ZIP, including any in-browser edits. */
export async function downloadAll(
  session: SessionCredentials,
  jobId: string,
  edits: Record<string, string>,
): Promise<void> {
  const response = await fetch(`${BASE}/api/v1/jobs/${jobId}/download`, {
    method: "POST",
    headers: { ...authHeaders(session), "Content-Type": "application/json" },
    body: JSON.stringify({
      files: Object.entries(edits).map(([id, markdown]) => ({ id, markdown })),
    }),
  });
  if (!response.ok) throw await toApiError(response);
  saveBlob(await response.blob(), "markpilot-results.zip");
}
