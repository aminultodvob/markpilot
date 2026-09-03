"use client";

/**
 * The converter.
 *
 * Two states: choose files, then review results. Everything is held in React
 * state and nothing is persisted - refreshing the page starts clean, which is
 * the honest behaviour for a tool that stores nothing.
 *
 * Progress is polled from the server and reflects real work. There are no
 * simulated progress bars anywhere: a file says "Recognizing text…" only
 * because the backend reported that it entered the OCR stage.
 */

import { AlertCircle, Lock, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AdvancedOptions } from "@/components/converter/AdvancedOptions";
import { Dropzone } from "@/components/converter/Dropzone";
import { PendingRow, type PendingFile } from "@/components/converter/FileQueue";
import { Workspace } from "@/components/converter/Workspace";
import { Button } from "@/components/ui/primitives";
import {
  ApiError,
  cancelJob,
  clearSession,
  createJob,
  downloadAll,
  downloadFile,
  fetchJob,
  fetchMarkdown,
  retryFile,
  warmUp,
} from "@/lib/api";
import { isSupported } from "@/lib/formats";
import {
  DEFAULT_SETTINGS,
  type ConversionSettings,
  type Job,
  type MarkdownResult,
  type SessionCredentials,
} from "@/lib/types";
import { plural } from "@/lib/utils";

const POLL_INTERVAL_MS = 700;
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

let keyCounter = 0;

export function Converter() {
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [settings, setSettings] = useState<ConversionSettings>(DEFAULT_SETTINGS);
  const [session, setSession] = useState<SessionCredentials | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, MarkdownResult>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [loadingResult, setLoadingResult] = useState(false);

  const sessionRef = useRef<SessionCredentials | null>(null);
  sessionRef.current = session;

  const busy = job !== null && !TERMINAL.has(job.status);

  // Wake a suspended free-tier converter while the user is still choosing a
  // file, so the cold start does not look like a stalled conversion.
  useEffect(() => {
    warmUp();
  }, []);

  // Release the server-side session when the tab goes away, so temporary
  // files are freed immediately rather than waiting for the TTL sweep.
  useEffect(() => {
    const release = () => {
      if (sessionRef.current) void clearSession(sessionRef.current);
    };
    window.addEventListener("pagehide", release);
    return () => window.removeEventListener("pagehide", release);
  }, []);

  // --- file selection ------------------------------------------------------

  const addFiles = useCallback((incoming: File[]) => {
    setError(null);
    setPending((current) => {
      const existing = new Set(current.map((p) => `${p.file.name}:${p.file.size}`));
      const additions: PendingFile[] = [];
      for (const file of incoming) {
        const identity = `${file.name}:${file.size}`;
        if (existing.has(identity)) continue;
        existing.add(identity);
        additions.push({
          key: `f${keyCounter++}`,
          file,
          error: isSupported(file.name)
            ? undefined
            : "This file type isn't supported.",
        });
      }
      return [...current, ...additions];
    });
  }, []);

  const removeFile = useCallback((key: string) => {
    setPending((current) => current.filter((entry) => entry.key !== key));
  }, []);

  // --- conversion ----------------------------------------------------------

  const convertible = pending.filter((entry) => !entry.error);

  const startConversion = useCallback(async () => {
    if (convertible.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      const created = await createJob(
        convertible.map((entry) => entry.file),
        settings,
      );
      const credentials: SessionCredentials = {
        sessionId: created.session_id,
        sessionToken: created.session_token,
      };
      setSession(credentials);
      setJob(created);
      setPending([]);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "We couldn't start the conversion. Please try again.",
      );
    } finally {
      setUploading(false);
    }
  }, [convertible, settings]);

  // Poll while work is outstanding.
  useEffect(() => {
    if (!session || !job || TERMINAL.has(job.status)) return;

    let active = true;
    const controller = new AbortController();
    const timer = setInterval(async () => {
      try {
        const next = await fetchJob(session, job.id, controller.signal);
        if (active) setJob(next);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404 && active) {
          setError("This session expired. Please upload your files again.");
          setJob(null);
          setSession(null);
        }
      }
    }, POLL_INTERVAL_MS);

    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [session, job]);

  // Select the first completed file automatically, so a single-file conversion
  // lands the user straight on their result.
  useEffect(() => {
    if (selectedId || !job) return;
    const first = job.files.find((file) => file.status === "completed");
    if (first) setSelectedId(first.id);
  }, [job, selectedId]);

  // Fetch the Markdown for whichever file is selected.
  useEffect(() => {
    if (!session || !job || !selectedId || results[selectedId]) return;
    const file = job.files.find((f) => f.id === selectedId);
    if (!file || file.status !== "completed") return;

    let active = true;
    setLoadingResult(true);
    fetchMarkdown(session, job.id, selectedId)
      .then((result) => {
        if (active) setResults((current) => ({ ...current, [selectedId]: result }));
      })
      .catch(() => {
        if (active) setError("We couldn't load that result.");
      })
      .finally(() => {
        if (active) setLoadingResult(false);
      });

    return () => {
      active = false;
    };
  }, [session, job, selectedId, results]);

  // --- actions -------------------------------------------------------------

  const handleCancel = useCallback(async () => {
    if (!session || !job) return;
    try {
      setJob(await cancelJob(session, job.id));
    } catch {
      setError("We couldn't cancel the conversion.");
    }
  }, [session, job]);

  const handleRetry = useCallback(
    async (fileId: string) => {
      if (!session || !job) return;
      try {
        setJob(await retryFile(session, job.id, fileId, settings));
      } catch (caught) {
        setError(
          caught instanceof ApiError ? caught.message : "We couldn't retry that file.",
        );
      }
    },
    [session, job, settings],
  );

  const handleClear = useCallback(async () => {
    if (session) await clearSession(session);
    setSession(null);
    setJob(null);
    setResults({});
    setEdits({});
    setSelectedId(null);
    setPending([]);
    setError(null);
  }, [session]);

  const currentMarkdown = selectedId
    ? (edits[selectedId] ?? results[selectedId]?.markdown ?? "")
    : "";

  const handleEdit = useCallback(
    (value: string) => {
      if (selectedId) setEdits((current) => ({ ...current, [selectedId]: value }));
    },
    [selectedId],
  );

  const handleDownload = useCallback(async () => {
    if (!session || !job || !selectedId) return;
    const result = results[selectedId];
    if (!result) return;
    try {
      await downloadFile(
        session,
        job.id,
        selectedId,
        result.output_filename,
        edits[selectedId],
      );
    } catch {
      setError("We couldn't download that file.");
    }
  }, [session, job, selectedId, results, edits]);

  const handleDownloadAll = useCallback(async () => {
    if (!session || !job) return;
    try {
      await downloadAll(session, job.id, edits);
    } catch {
      setError("We couldn't build the ZIP download.");
    }
  }, [session, job, edits]);

  // --- render --------------------------------------------------------------

  const showWorkspace = job !== null;

  return (
    <div className="space-y-4">
      {/* Live region so status changes reach screen readers. */}
      <div aria-live="polite" className="sr-only">
        {busy
          ? `Converting. ${job?.completed_count ?? 0} of ${plural(job?.file_count ?? 0, "file")} done.`
          : job
            ? `Conversion finished. ${job.completed_count} of ${plural(job.file_count, "file")} converted.`
            : ""}
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-[var(--radius-control)] border px-3 py-2.5 text-[13px]"
          style={{
            background: "var(--danger-subtle)",
            borderColor: "transparent",
            color: "var(--danger)",
          }}
        >
          <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden />
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
            <X size={15} aria-hidden />
          </button>
        </div>
      )}

      {showWorkspace ? (
        <div className="animate-rise">
          <Workspace
            files={job.files}
            selectedId={selectedId}
            result={selectedId ? (results[selectedId] ?? null) : null}
            markdown={currentMarkdown}
            loadingResult={loadingResult}
            isEdited={selectedId ? selectedId in edits : false}
            busy={busy}
            onSelect={setSelectedId}
            onRetry={handleRetry}
            onEdit={handleEdit}
            onDownload={handleDownload}
            onDownloadAll={handleDownloadAll}
            onClear={handleClear}
          />
          {busy && (
            <div className="mt-3 flex justify-center">
              <Button variant="ghost" size="sm" onClick={handleCancel}>
                Cancel conversion
              </Button>
            </div>
          )}
        </div>
      ) : (
        <>
          <Dropzone onFiles={addFiles} disabled={uploading} compact={pending.length > 0} />

          {pending.length > 0 && (
            <div
              className="animate-rise overflow-hidden rounded-[var(--radius-card)] border"
              style={{
                background: "var(--surface)",
                borderColor: "var(--border)",
                boxShadow: "var(--shadow-soft)",
              }}
            >
              <div
                className="flex items-center justify-between border-b px-4 py-2.5"
                style={{ borderColor: "var(--border)" }}
              >
                <h2
                  className="text-[11px] font-semibold tracking-[0.06em] uppercase"
                  style={{ color: "var(--text-faint)" }}
                >
                  {plural(pending.length, "file")} ready
                </h2>
                <button
                  type="button"
                  onClick={() => setPending([])}
                  className="rounded px-1.5 py-0.5 text-[12px] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
                  style={{ color: "var(--text-muted)" }}
                >
                  Remove all
                </button>
              </div>
              <ul
                className="divide-y px-1 py-1"
                style={{ borderColor: "var(--border)" }}
              >
                {pending.map((entry) => (
                  <PendingRow
                    key={entry.key}
                    entry={entry}
                    onRemove={() => removeFile(entry.key)}
                  />
                ))}
              </ul>
            </div>
          )}

          {/* Options and the primary action appear only once there is
              something to convert. Before that the dropzone is the call to
              action, and a greyed-out button beside it is just noise. */}
          {pending.length > 0 && (
            <div className="animate-rise flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
              <AdvancedOptions
                settings={settings}
                onChange={setSettings}
                disabled={uploading}
              />
              <Button
                variant="primary"
                size="lg"
                onClick={startConversion}
                loading={uploading}
                disabled={convertible.length === 0}
                icon={!uploading ? <Sparkles size={16} /> : undefined}
                className="w-full sm:w-auto"
              >
                {uploading
                  ? "Uploading…"
                  : convertible.length > 1
                    ? `Convert ${convertible.length} files`
                    : "Convert to Markdown"}
              </Button>
            </div>
          )}

          <p
            className="flex items-center justify-center gap-1.5 text-[12.5px]"
            style={{ color: "var(--text-faint)" }}
          >
            <Lock size={12} aria-hidden />
            Processed temporarily · Never stored permanently
          </p>
        </>
      )}
    </div>
  );
}
