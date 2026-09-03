"use client";

/**
 * The result workspace.
 *
 * Built as a reading surface, in the spirit of Claude's artifact panel: a slim
 * file rail on the left, and the document on the right that eases into place
 * when you open it. Any document can be expanded into a full-screen reader -
 * a large, centred column on a dimmed backdrop - for distraction-free reading
 * of a long conversion. Every transition uses the same gentle spring, so
 * opening, switching and expanding all feel like turning a page rather than
 * swapping a screen.
 *
 * Mobile is not this layout shrunk down. Tapping a file slides the document up
 * as a full-height sheet with a back control, which is the only sane shape for
 * a document reader at 375px.
 */

import {
  ArrowLeft,
  Check,
  ChevronDown,
  Code2,
  Copy,
  Download,
  Eye,
  FileText,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  ScanText,
  Trash2,
  X,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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

const VIEW_OPTIONS = [
  { value: "preview" as const, label: "Preview", icon: <Eye size={13} /> },
  { value: "markdown" as const, label: "Markdown", icon: <Code2 size={13} /> },
];

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
  const [mobilePane, setMobilePane] = useState<MobilePane>("files");
  const [railWidth, setRailWidth] = useState(300);
  const [railOpen, setRailOpen] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const completed = files.filter((f) => f.status === "completed").length;
  const multiple = files.length > 1;

  // --- full-screen reader: scroll lock + Escape to close -------------------

  useEffect(() => {
    if (!expanded) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [expanded]);

  // Expanding only makes sense with a document open.
  useEffect(() => {
    if (!selectedId) setExpanded(false);
  }, [selectedId]);

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

  // --- file rail -----------------------------------------------------------

  const fileRail = (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between px-4 pt-4 pb-2">
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

  // --- document view -------------------------------------------------------
  // One renderer, used in three places: the desktop split, the mobile sheet,
  // and the full-screen reader. `fullscreen` only widens the reading column
  // and swaps the header controls.

  const metadata = result?.metadata;

  const renderDocument = (context: "split" | "sheet" | "reader") => {
    const isReader = context === "reader";

    const header = (
      <header
        className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2.5 sm:px-4"
        style={{ borderColor: "var(--border)" }}
      >
        {/* Left cluster: a context-appropriate leading control. */}
        {context === "sheet" ? (
          <button
            type="button"
            onClick={() => setMobilePane("files")}
            className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] font-medium transition-colors hover:bg-[var(--surface-sunken)]"
            style={{ color: "var(--text-secondary)" }}
          >
            <ArrowLeft size={15} aria-hidden />
            Files
          </button>
        ) : context === "split" ? (
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
        ) : null}

        <div className="flex min-w-0 flex-1 items-center gap-2">
          <FileText
            size={14}
            aria-hidden
            className="shrink-0"
            style={{ color: "var(--text-faint)" }}
          />
          {result ? (
            <>
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
            </>
          ) : (
            <span className="text-[13.5px]" style={{ color: "var(--text-muted)" }}>
              No file selected
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <Segmented
            label="Document view"
            size="sm"
            value={view}
            onChange={setView}
            options={VIEW_OPTIONS}
          />
          <div
            className="hidden h-5 w-px sm:block"
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

          {/* Reader controls, mirroring Claude's expand / close affordances. */}
          {context !== "sheet" && (
            <>
              <div
                className="h-5 w-px"
                style={{ background: "var(--border)" }}
                aria-hidden
              />
              <IconButton
                label={isReader ? "Exit full screen" : "Open full screen"}
                onClick={() => setExpanded(!isReader)}
                disabled={!markdown}
                icon={
                  isReader ? <Minimize2 size={15} /> : <Maximize2 size={15} />
                }
              />
              {isReader && (
                <IconButton
                  label="Close reader"
                  onClick={() => setExpanded(false)}
                  icon={<X size={16} />}
                />
              )}
            </>
          )}
        </div>
      </header>
    );

    const metaStrip = metadata && (
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
    );

    const warnings = result && result.warnings.length > 0 && (
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
    );

    // While the reader is open, the split/sheet behind it shows a calm hint
    // instead of a second live copy of the document (and a second editor).
    const supersededByReader = !isReader && expanded && Boolean(selectedId);

    const body = (
      <div
        className="min-h-0 flex-1 overflow-y-auto scroll-smooth"
        style={{
          background:
            view === "preview" ? "var(--bg-subtle)" : "var(--surface)",
        }}
      >
        {supersededByReader ? (
          <div
            className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center"
            style={{ color: "var(--text-muted)" }}
          >
            <Maximize2 size={20} aria-hidden strokeWidth={1.75} />
            <p className="text-sm">Reading in full screen.</p>
            <Button size="sm" variant="secondary" onClick={() => setExpanded(false)}>
              Exit full screen
            </Button>
          </div>
        ) : loadingResult ? (
          <div
            className="flex h-full items-center justify-center gap-2 text-sm"
            style={{ color: "var(--text-muted)" }}
          >
            <Spinner /> Loading document…
          </div>
        ) : !selectedId ? (
          <EmptyDocument busy={busy} />
        ) : view === "preview" ? (
          <div
            className={cx(
              "px-4 py-8 sm:px-8",
              isReader ? "sm:py-14" : "sm:py-12",
            )}
          >
            {/* Keyed on the file + view so opening or switching eases in. */}
            <article
              key={`${selectedId}-${isReader}`}
              className={cx(
                "animate-doc-in mx-auto rounded-[var(--radius-card)] px-5 py-8 sm:px-12 sm:py-14",
                isReader ? "max-w-[62rem]" : "max-w-[52rem]",
              )}
              style={{
                background: "var(--surface)",
                boxShadow: "var(--shadow-lift)",
              }}
            >
              <MarkdownPreview markdown={markdown} />
            </article>
          </div>
        ) : (
          <div key={selectedId} className="animate-fade-in h-full">
            <MarkdownEditor
              value={markdown}
              onChange={onEdit}
              label={
                result ? `Markdown source of ${result.filename}` : undefined
              }
            />
          </div>
        )}
      </div>
    );

    return (
      <div className="flex h-full min-h-0 flex-col">
        {header}
        {metaStrip}
        {warnings}
        {body}
      </div>
    );
  };

  // --- assembly ------------------------------------------------------------

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
              <Check size={14} aria-hidden style={{ color: "var(--success)" }} />
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

      {/* Mobile: file list, with the document sliding up as a full sheet */}
      <div className="relative lg:hidden">
        <div className="h-[72vh] min-h-[460px] overflow-y-auto">{fileRail}</div>
        {selectedId && mobilePane === "document" && (
          <div
            className="animate-doc-in absolute inset-0 z-10"
            style={{ background: "var(--surface)" }}
          >
            {renderDocument("sheet")}
          </div>
        )}
      </div>

      {/* Desktop: rail + document, split */}
      <div ref={containerRef} className="hidden h-[80vh] min-h-[560px] lg:flex">
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
        <div className="min-w-0 flex-1">{renderDocument("split")}</div>
      </div>

      {/*
        Full-screen reader, rendered through a portal to document.body.
        The workspace sits inside an element with an entrance animation whose
        `animation-fill-mode: both` leaves an identity-matrix transform behind,
        and *any* transform makes an element the containing block for
        position:fixed - which would box the reader inside the workspace. The
        portal sidesteps that entirely, so the overlay always fills the true
        viewport.
      */}
      {expanded &&
        selectedId &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-stretch justify-center p-0 sm:items-center sm:p-6 lg:p-10"
            role="dialog"
            aria-modal="true"
            aria-label={result ? `Reading ${result.filename}` : "Document reader"}
          >
            <button
              type="button"
              aria-label="Close reader"
              onClick={() => setExpanded(false)}
              className="animate-fade-in absolute inset-0 cursor-default"
              style={{
                // A warm-dark scrim, fixed rather than theme-derived: it must
                // darken the page in *light* mode too, so the document card
                // reads as lifted above it in both themes.
                background: "rgba(24, 18, 12, 0.5)",
                backdropFilter: "blur(6px)",
                WebkitBackdropFilter: "blur(6px)",
              }}
            />
            <div
              className="animate-reader-in relative flex w-full max-w-[75rem] flex-col overflow-hidden sm:h-[92vh] sm:rounded-[var(--radius-card)]"
              style={{
                height: "100dvh",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                boxShadow: "var(--shadow-float)",
              }}
            >
              {renderDocument("reader")}
            </div>
          </div>,
          document.body,
        )}
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
