"use client";

import { FileUp } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { ACCEPT_ATTRIBUTE, HEADLINE_FORMATS } from "@/lib/formats";
import { cx } from "@/lib/utils";

interface DropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  compact?: boolean;
}

/**
 * The primary upload target.
 *
 * Drag-and-drop is an enhancement, never a requirement: the whole surface is a
 * real `<label>` bound to a file input, so clicking, tapping and keyboard
 * activation all work and screen readers announce it as a file control.
 *
 * A window-level drag listener lifts the zone as soon as a file enters the
 * page, so the target announces itself before the pointer reaches it.
 */
export function Dropzone({ onFiles, disabled = false, compact = false }: DropzoneProps) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);
  const [windowDrag, setWindowDrag] = useState(false);
  // Drag events fire for every child element, so nesting is counted.
  const dragDepth = useRef(0);

  const handleFiles = useCallback(
    (list: FileList | null) => {
      if (!list || list.length === 0) return;
      onFiles(Array.from(list));
    },
    [onFiles],
  );

  // Highlight the zone whenever a file is dragged anywhere over the page.
  useEffect(() => {
    if (disabled) return;
    let depth = 0;
    const hasFiles = (event: DragEvent) =>
      Array.from(event.dataTransfer?.types ?? []).includes("Files");

    const onEnter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth += 1;
      setWindowDrag(true);
    };
    const onLeave = () => {
      depth = Math.max(0, depth - 1);
      if (depth === 0) setWindowDrag(false);
    };
    const onDrop = () => {
      depth = 0;
      setWindowDrag(false);
    };
    // Without preventDefault the browser navigates to the dropped file.
    const onOver = (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
    };

    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
  }, [disabled]);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      setWindowDrag(false);
      if (!disabled) handleFiles(event.dataTransfer.files);
    },
    [disabled, handleFiles],
  );

  const active = dragging || windowDrag;

  return (
    <div className="w-full">
      <input
        id={inputId}
        type="file"
        multiple
        accept={ACCEPT_ATTRIBUTE}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => {
          handleFiles(event.target.files);
          // Reset so choosing the same file twice still fires a change.
          event.target.value = "";
        }}
      />

      <label
        htmlFor={inputId}
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepth.current += 1;
          if (!disabled) setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (dragDepth.current === 0) setDragging(false);
        }}
        onDrop={onDrop}
        className={cx(
          "group relative flex w-full cursor-pointer flex-col items-center justify-center",
          "overflow-hidden text-center",
          "transition-[border-color,background-color,transform,box-shadow] duration-200",
          compact ? "gap-2 px-6 py-9" : "gap-4 px-6 py-16 sm:py-20",
          disabled && "pointer-events-none opacity-60",
        )}
        style={{
          borderRadius: "var(--radius-card)",
          border: `1.5px dashed ${
            active ? "var(--accent)" : "var(--border-strong)"
          }`,
          background: active ? "var(--accent-subtle)" : "var(--surface)",
          boxShadow: active ? "var(--shadow-lift)" : "var(--shadow-soft)",
          transform: dragging ? "scale(1.004)" : undefined,
        }}
      >
        {/* Icon with a ring that pulses only while a file is over the page. */}
        <span className="relative flex items-center justify-center">
          {active && (
            <span
              className="animate-pulse-ring absolute inset-0 rounded-full"
              style={{ background: "var(--accent)", opacity: 0.25 }}
              aria-hidden
            />
          )}
          <span
            className={cx(
              "relative flex items-center justify-center rounded-full",
              "transition-transform duration-200 group-hover:-translate-y-0.5",
            )}
            style={{
              width: compact ? 40 : 56,
              height: compact ? 40 : 56,
              background: active ? "var(--accent)" : "var(--surface-sunken)",
              color: active ? "var(--accent-contrast)" : "var(--text-muted)",
            }}
          >
            <FileUp size={compact ? 18 : 22} aria-hidden strokeWidth={1.75} />
          </span>
        </span>

        <span className="flex flex-col gap-1.5">
          <span
            className={cx(
              "font-semibold tracking-[-0.01em]",
              compact ? "text-[15px]" : "text-lg sm:text-xl",
            )}
            style={{ fontFamily: "var(--font-serif)" }}
          >
            {active ? "Release to add your files" : "Drop a document to begin"}
          </span>

          {!active && (
            <span className="text-[13.5px]" style={{ color: "var(--text-muted)" }}>
              or{" "}
              <span
                className="font-medium underline decoration-[1.5px] underline-offset-[3px]"
                style={{
                  color: "var(--accent)",
                  textDecorationColor: "var(--accent-border)",
                }}
              >
                browse your files
              </span>
            </span>
          )}
        </span>

        {!compact && !active && (
          <span
            className="mt-1 flex flex-wrap items-center justify-center gap-x-2 gap-y-1"
            aria-hidden
          >
            {HEADLINE_FORMATS.map((format) => (
              <span
                key={format}
                className="rounded-[var(--radius-pill)] px-2 py-0.5 font-mono text-[10.5px] tracking-wide"
                style={{
                  background: "var(--surface-sunken)",
                  color: "var(--text-faint)",
                }}
              >
                {format}
              </span>
            ))}
          </span>
        )}
      </label>
    </div>
  );
}
