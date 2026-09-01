"use client";

import { AlertCircle, Check, RotateCcw, ScanText, X } from "lucide-react";
import { useState } from "react";

import { Badge, Button, FormatTag, Spinner } from "@/components/ui/primitives";
import { badgeFor } from "@/lib/formats";
import type { ConversionStage, FileResult } from "@/lib/types";
import { cx, formatBytes, formatDuration } from "@/lib/utils";

/** What each real pipeline stage is called in the UI. */
const STAGE_LABEL: Record<ConversionStage, string> = {
  detecting: "Checking file",
  converting: "Converting",
  ocr: "Reading text",
  finalizing: "Finishing",
};

/** A file chosen but not yet uploaded. */
export interface PendingFile {
  key: string;
  file: File;
  error?: string;
}

export function PendingRow({
  entry,
  onRemove,
}: {
  entry: PendingFile;
  onRemove: () => void;
}) {
  const invalid = Boolean(entry.error);
  return (
    <li className="group flex items-center gap-3 px-3 py-2.5">
      <FormatTag label={badgeFor(entry.file.name)} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium">{entry.file.name}</p>
        <p
          className="mt-0.5 text-[12px]"
          style={{ color: invalid ? "var(--danger)" : "var(--text-muted)" }}
        >
          {invalid ? entry.error : formatBytes(entry.file.size)}
        </p>
      </div>
      {invalid && <Badge tone="danger">Unsupported</Badge>}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${entry.file.name}`}
        className="rounded-md p-1.5 opacity-0 transition-all group-hover:opacity-100 focus-visible:opacity-100 hover:bg-[var(--surface-sunken)]"
        style={{ color: "var(--text-muted)" }}
      >
        <X size={15} aria-hidden />
      </button>
    </li>
  );
}

function StatusLine({ file }: { file: FileResult }) {
  if (file.status === "completed") {
    const meta = file.metadata;
    return (
      <span
        className="flex items-center gap-1.5 text-[11.5px]"
        style={{ color: "var(--text-muted)" }}
      >
        <Check size={12} aria-hidden style={{ color: "var(--success)" }} />
        {meta
          ? `${meta.pages ? `${meta.pages}p · ` : ""}${formatDuration(meta.duration_ms)}`
          : "Done"}
      </span>
    );
  }

  if (file.status === "processing") {
    const stage = file.stage ?? "converting";
    const isOcr = stage === "ocr";
    return (
      <span
        className="flex items-center gap-1.5 text-[11.5px]"
        style={{ color: isOcr ? "var(--accent)" : "var(--text-muted)" }}
      >
        {isOcr ? <ScanText size={12} aria-hidden /> : <Spinner size={11} />}
        {STAGE_LABEL[stage]}
        <span className="inline-flex gap-0.5" aria-hidden>
          <Dot delay={0} />
          <Dot delay={160} />
          <Dot delay={320} />
        </span>
      </span>
    );
  }

  if (file.status === "failed") {
    return (
      <span
        className="flex items-center gap-1.5 text-[11.5px] whitespace-nowrap"
        style={{ color: "var(--danger)" }}
      >
        <AlertCircle size={12} aria-hidden className="shrink-0" />
        Failed
      </span>
    );
  }

  if (file.status === "cancelled") {
    return (
      <span className="text-[11.5px]" style={{ color: "var(--text-muted)" }}>
        Cancelled
      </span>
    );
  }

  return (
    <span className="text-[11.5px]" style={{ color: "var(--text-muted)" }}>
      Waiting
    </span>
  );
}

/** Three dots that breathe while work is genuinely in progress. */
function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="inline-block h-[3px] w-[3px] rounded-full"
      style={{
        background: "currentColor",
        animation: "pulse 1.2s ease-in-out infinite",
        animationDelay: `${delay}ms`,
      }}
    />
  );
}

export function ResultRow({
  file,
  selected,
  onSelect,
  onRetry,
}: {
  file: FileResult;
  selected: boolean;
  onSelect: () => void;
  onRetry: () => void;
}) {
  const [showDetail, setShowDetail] = useState(false);
  const selectable = file.status === "completed";
  const ocrUsed = file.metadata?.ocr_used ?? false;

  return (
    <li>
      <div
        className={cx(
          "flex items-center gap-2.5 rounded-[10px] px-2.5 py-2 transition-colors duration-150",
          selectable && !selected && "hover:bg-[var(--surface-sunken)]",
          selectable && "cursor-pointer",
        )}
        style={{
          background: selected ? "var(--surface)" : undefined,
          boxShadow: selected ? "var(--shadow-soft)" : undefined,
        }}
        onClick={selectable ? onSelect : undefined}
        onKeyDown={
          selectable
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect();
                }
              }
            : undefined
        }
        role={selectable ? "button" : undefined}
        tabIndex={selectable ? 0 : undefined}
        aria-current={selected || undefined}
      >
        {/* A thin accent spine marks the open document. */}
        <span
          aria-hidden
          className="h-8 w-[2.5px] shrink-0 rounded-full transition-colors"
          style={{ background: selected ? "var(--accent)" : "transparent" }}
        />

        <FormatTag label={badgeFor(file.filename)} />

        <div className="min-w-0 flex-1">
          <p
            className="truncate text-[13px]"
            style={{ fontWeight: selected ? 600 : 500 }}
            title={file.filename}
          >
            {file.filename}
          </p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <StatusLine file={file} />
            {ocrUsed && (
              <span
                className="text-[10.5px] font-medium"
                style={{ color: "var(--accent)" }}
              >
                OCR
              </span>
            )}
          </div>
          {file.source_archive && (
            <p
              className="mt-0.5 truncate text-[10.5px]"
              style={{ color: "var(--text-faint)" }}
            >
              from {file.source_archive}
            </p>
          )}
        </div>

        {file.status === "failed" && (
          <Button
            size="sm"
            variant="ghost"
            icon={<RotateCcw size={12} />}
            onClick={(event) => {
              event.stopPropagation();
              onRetry();
            }}
          >
            Retry
          </Button>
        )}
      </div>

      {file.status === "failed" && file.error && (
        <div className="px-3 pt-0.5 pb-2.5 pl-[3.4rem]">
          <p
            className="text-[11.5px] leading-relaxed"
            style={{ color: "var(--text-secondary)" }}
          >
            {file.error.message}
          </p>
          {file.error.detail && (
            <>
              <button
                type="button"
                onClick={() => setShowDetail((value) => !value)}
                className="mt-1 text-[11px] underline underline-offset-2"
                style={{ color: "var(--text-faint)" }}
                aria-expanded={showDetail}
              >
                {showDetail ? "Hide details" : "Show technical details"}
              </button>
              {showDetail && (
                <pre
                  className="mt-1.5 max-h-32 overflow-auto rounded-lg p-2 font-mono text-[10.5px] whitespace-pre-wrap"
                  style={{
                    background: "var(--surface-sunken)",
                    color: "var(--text-muted)",
                  }}
                >
                  {file.error.code}: {file.error.detail}
                </pre>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}
