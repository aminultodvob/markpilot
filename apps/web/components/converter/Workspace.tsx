"use client";

/**
 * The result workspace.
 *
 * Built as a reading surface rather than a dashboard. The document sits on a
 * paper-coloured panel in a measured column, the chrome around it is thin and
 * quiet, and the file list is a rail that can be folded away entirely when
 * someone just wants to read.
 *
 * Mobile is not this layout shrunk down - a side-by-side split at 375px is
 * unusable - so it becomes a three-way pane switcher with the same surfaces.
 */

import {
  Check,
  ChevronDown,
  Copy,
  Download,
  FileText,
  PanelLeftClose,
  PanelLeftOpen,
  ScanText,
  Trash2,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import { ResultRow } from "@/components/converter/FileQueue";
import { MarkdownPreview } from "@/components/converter/MarkdownPreview";
import {
  Badge,
  Button,
  IconButton,
  Segmented,
  Spinner,
} from "@/components/ui/primitives";
import type { FileResult, MarkdownResult } from "@/lib/types";
import { cx, formatDuration, plural } from "@/lib/utils";

// The editor is the heaviest thing on the page and is useless until a result
// exists, so it never joins the initial bundle.
const MarkdownEditor = dynamic(() => import("./MarkdownEditor"), {
  ssr: false,
  loading: () => (
    <div
      className="flex h-full items-center justify-center gap-2 text-sm"
      style={{ color: "var(--text-muted)" }}
    >
      <Spinner /> Loading editor…
    </div>
  ),
});

type View = "preview" | "markdown";
type MobilePane = "files" | "document";

const MIN_RAIL = 232;
const MAX_RAIL = 400;

interface Props {
  files: FileResult[];
  selectedId: string | null;
  result: MarkdownResult | null;
  markdown: string;
  loadingResult: boolean;
  isEdited: boolean;
  busy: boolean;
  onSelect: (fileId: string) => void;
  onRetry: (fileId: string) => void;
  onEdit: (value: string) => void;
  onDownload: () => void;
  onDownloadAll: () => void;
  onClear: () => void;
}

export function Workspace({
  files,
  selectedId,
  result,
  markdown,
  loadingResult,
  isEdited,
  busy,
  onSelect,
  onRetry,
  onEdit,
  onDownload,
  onDownloadAll,
  onClear,
}: Props) {
  const [view, setView] = useState<View>("preview");
  const [mobilePane, setMobilePane] = useState<MobilePane>("document");
  const [railWidth, setRailWidth] = useState(282);
  const [railOpen, setRailOpen] = useState(true);
  const [copied, setCopied] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const completed = files.filter((f) => f.status === "completed").length;
  const multiple = files.length > 1;

  // --- resizable rail ------------------------------------------------------

  useEffect(() => {
    const onMove = (event: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const left = containerRef.current.getBoundingClientRect().left;
      setRailWidth(
        Math.min(Math.max(event.clientX - left, MIN_RAIL), MAX_RAIL),
      );
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const startDrag = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard access can be blocked; the Markdown tab still allows
      // selecting and copying by hand.
    }
  }, [markdown]);

  // --- panes ---------------------------------------------------------------

  const fileRail = (
    <div className="flex h-full flex-col">
      <div
        className="flex shrink-0 items-center justify-between px-4 pt-4 pb-2"
      >
        <h2
          className="text-[11px] font-semibold tracking-[0.06em] uppercase"
          style={{ color: "var(--text-faint)" }}
        >
          {plural(files.length, "file")}
        </h2>
        {busy && <Spinner size={12} />}
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {files.map((file) => (
          <ResultRow
            key={file.id}
            file={file}
            selected={file.id === selectedId}
            onSelect={() => {
              onSelect(file.id);
              setMobilePane("document");
            }}
            onRetry={() => onRetry(file.id)}
          />
        ))}
      </ul>
    </div>
  );

  const metadata = result?.metadata;

  const documentPane = (
    <div className="flex h-full min-h-0 flex-col">
      {/* Document header: identity on the left, actions on the right. */}
      <header
        className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2.5 sm:px-4"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="hidden lg:block">
          <IconButton
            label={railOpen ? "Hide file list" : "Show file list"}
            onClick={() => setRailOpen((open) => !open)}
            icon={
              railOpen ? (
                <PanelLeftClose size={16} />
              ) : (
                <PanelLeftOpen size={16} />
              )
            }
          />
        </div>

        <div className="min-w-0 flex-1">
          {result ? (
            <div className="flex min-w-0 items-center gap-2">
              <span
                className="truncate text-[13.5px] font-medium"
                title={result.filename}
              >
                {result.filename}
              </span>
              {isEdited && (
                <span
                  className="shrink-0 text-[11px]"
                  style={{ color: "var(--text-faint)" }}
                >
                  · edited
                </span>
              )}
            </div>
          ) : (
            <span className="text-[13.5px]" style={{ color: "var(--text-muted)" }}>
              No file selected
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Segmented
            label="Document view"
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: "preview", label: "Preview" },
              { value: "markdown", label: "Markdown" },
            ]}
          />
          <div
            className="h-5 w-px"
            style={{ background: "var(--border)" }}
            aria-hidden
          />
          <Button
            size="sm"
            variant="ghost"
            onClick={copy}
            disabled={!markdown}
            icon={copied ? <Check size={13} /> : <Copy size={13} />}
          >
            <span className="hidden sm:inline">{copied ? "Copied" : "Copy"}</span>
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={onDownload}
            disabled={!markdown}
            icon={<Download size={13} />}
          >
            <span className="hidden sm:inline">Download</span>
          </Button>
        </div>
      </header>

      {/* A quiet metadata strip; the full detail is behind a disclosure. */}
      {metadata && (
        <div
          className="shrink-0 border-b px-3 sm:px-4"
          style={{ borderColor: "var(--border)" }}
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-[11.5px]">
            <span
              className="font-mono tracking-wide uppercase"
              style={{ color: "var(--text-faint)" }}
            >
              {metadata.label}
            </span>
            {metadata.pages ? (
              <span style={{ color: "var(--text-muted)" }}>
                {plural(metadata.pages, "page")}
              </span>
            ) : null}
            <span style={{ color: "var(--text-muted)" }}>
              {plural(metadata.word_count, "word")}
            </span>
            <span style={{ color: "var(--text-muted)" }}>
              {formatDuration(metadata.duration_ms)}
            </span>
            {metadata.ocr_used && (
              <Badge tone="accent">
                <ScanText size={10} aria-hidden />
                OCR
                {metadata.ocr_confidence !== undefined &&
                  ` ${Math.round(metadata.ocr_confidence)}%`}
              </Badge>
            )}
            <button
              type="button"
              onClick={() => setDetailsOpen((open) => !open)}
              aria-expanded={detailsOpen}
              className="ml-auto inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors hover:bg-[var(--surface-sunken)]"
              style={{ color: "var(--text-faint)" }}
            >
              Details
              <ChevronDown
                size={12}
                aria-hidden
                className={cx("transition-transform", detailsOpen && "rotate-180")}
              />
            </button>
          </div>

          {detailsOpen && (
            <dl
              className="grid grid-cols-2 gap-x-6 gap-y-1 pb-3 text-[11.5px] sm:grid-cols-3"
              style={{ color: "var(--text-muted)" }}
            >
              <div>
                <dt className="inline" style={{ color: "var(--text-faint)" }}>
                  Engine:{" "}
                </dt>
                <dd className="inline">{metadata.engine}</dd>
              </div>
              <div>
                <dt className="inline" style={{ color: "var(--text-faint)" }}>
                  Characters:{" "}
                </dt>
                <dd className="inline">
                  {metadata.character_count.toLocaleString()}
                </dd>
              </div>
              {metadata.ocr_languages && (
                <div>
                  <dt className="inline" style={{ color: "var(--text-faint)" }}>
                    OCR languages:{" "}
                  </dt>
                  <dd className="inline">{metadata.ocr_languages}</dd>
                </div>
              )}
            </dl>
          )}
        </div>
      )}

      {/* Warnings sit above the document, where they cannot be missed. */}
      {result && result.warnings.length > 0 && (
        <div
          className="shrink-0 border-b px-3 py-2 sm:px-4"
          style={{
            borderColor: "var(--border)",
            background: "var(--warning-subtle)",
          }}
        >
          <ul className="space-y-0.5">
            {result.warnings.map((warning) => (
              <li
                key={warning}
                className="text-[12px] leading-relaxed"
                style={{ color: "var(--warning)" }}
              >
                {warning}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* The document itself. */}
      <div
        className="min-h-0 flex-1 overflow-y-auto"
        style={{
          background: view === "preview" ? "var(--bg-subtle)" : "var(--surface)",
        }}
      >
        {loadingResult ? (
          <div
            className="flex h-full items-center justify-center gap-2 text-sm"
            style={{ color: "var(--text-muted)" }}
          >
            <Spinner /> Loading document…
          </div>
        ) : !selectedId ? (
          <EmptyDocument busy={busy} />
        ) : view === "preview" ? (
          <div className="px-4 py-8 sm:px-8 sm:py-12">
            <article
              className="animate-rise mx-auto max-w-[52rem] rounded-[var(--radius-card)] px-5 py-8 sm:px-12 sm:py-14"
              style={{
                background: "var(--surface)",
                boxShadow: "var(--shadow-lift)",
              }}
            >
              <MarkdownPreview markdown={markdown} />
            </article>
          </div>
        ) : (
          <MarkdownEditor
            value={markdown}
            onChange={onEdit}
            label={result ? `Markdown source of ${result.filename}` : undefined}
          />
        )}
      </div>
    </div>
  );

  return (
    <div
      className="overflow-hidden rounded-[var(--radius-card)] border"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        boxShadow: "var(--shadow-lift)",
      }}
    >
      {/* Job toolbar */}
      <div
        className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2.5 sm:px-4"
        style={{ borderColor: "var(--border)", background: "var(--surface-sunken)" }}
      >
        <p className="flex items-center gap-2 text-[13px]">
          {busy ? (
            <>
              <Spinner size={13} />
              <span style={{ color: "var(--text-secondary)" }}>
                Converting… {completed} of {files.length} done
              </span>
            </>
          ) : (
            <>
              <Check
                size={14}
                aria-hidden
                style={{ color: "var(--success)" }}
              />
              <span style={{ color: "var(--text-secondary)" }}>
                {completed === files.length
                  ? `${plural(files.length, "file")} converted`
                  : `${completed} of ${files.length} converted`}
              </span>
            </>
          )}
        </p>
        <div className="flex items-center gap-1.5">
          {multiple && (
            <Button
              size="sm"
              variant="secondary"
              onClick={onDownloadAll}
              disabled={completed === 0}
              icon={<Download size={13} />}
            >
              Download all
            </Button>
          )}
          <Button
            size="sm"
            variant="danger"
            onClick={onClear}
            icon={<Trash2 size={13} />}
          >
            Clear
          </Button>
        </div>
      </div>

      {/* Mobile: pane switcher */}
      <div className="lg:hidden">
        <div
          role="tablist"
          aria-label="Workspace panes"
          className="grid grid-cols-2 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          {(["files", "document"] as const).map((pane) => (
            <button
              key={pane}
              role="tab"
              aria-selected={mobilePane === pane}
              onClick={() => setMobilePane(pane)}
              className="border-b-2 py-2.5 text-[13px] font-medium capitalize transition-colors"
              style={{
                borderBottomColor:
                  mobilePane === pane ? "var(--accent)" : "transparent",
                color: mobilePane === pane ? "var(--accent)" : "var(--text-muted)",
              }}
            >
              {pane === "files" ? `Files (${files.length})` : "Document"}
            </button>
          ))}
        </div>
        <div className="h-[68vh] min-h-[440px]">
          {mobilePane === "files" ? (
            <div className="h-full overflow-y-auto">{fileRail}</div>
          ) : (
            documentPane
          )}
        </div>
      </div>

      {/* Desktop: resizable rail + document */}
      <div ref={containerRef} className="hidden h-[74vh] min-h-[520px] lg:flex">
        {railOpen && (
          <>
            <div
              className="shrink-0 overflow-hidden"
              style={{ width: railWidth, background: "var(--bg-subtle)" }}
            >
              {fileRail}
            </div>
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize file list"
              tabIndex={0}
              onMouseDown={startDrag}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft") {
                  setRailWidth((w) => Math.max(w - 24, MIN_RAIL));
                }
                if (event.key === "ArrowRight") {
                  setRailWidth((w) => Math.min(w + 24, MAX_RAIL));
                }
              }}
              className="group w-px shrink-0 cursor-col-resize transition-colors hover:bg-[var(--accent)] focus-visible:bg-[var(--accent)]"
              style={{ background: "var(--border)" }}
            />
          </>
        )}
        <div className="min-w-0 flex-1">{documentPane}</div>
      </div>
    </div>
  );
}

function EmptyDocument({ busy }: { busy: boolean }) {
  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center"
      style={{ color: "var(--text-muted)" }}
    >
      <span
        className="flex h-12 w-12 items-center justify-center rounded-full"
        style={{ background: "var(--surface-sunken)" }}
      >
        <FileText size={20} aria-hidden strokeWidth={1.75} />
      </span>
      <p className="text-sm">
        {busy
          ? "Your document will appear here as soon as it's ready."
          : "Select a file to read its Markdown."}
      </p>
    </div>
  );
}
