"use client";

import { ChevronDown, Settings2 } from "lucide-react";
import { useId, useState } from "react";

import type { ConversionSettings, OcrLanguage, OcrMode } from "@/lib/types";
import { cx } from "@/lib/utils";

const OCR_MODES: Array<{ value: OcrMode; label: string; hint: string }> = [
  { value: "auto", label: "Auto", hint: "Use OCR only when a page has no text" },
  { value: "force", label: "Always", hint: "Run OCR even if text is available" },
  { value: "off", label: "Off", hint: "Never run OCR" },
];

const LANGUAGES: Array<{ value: OcrLanguage; label: string }> = [
  { value: "auto", label: "Auto detect" },
  { value: "eng", label: "English" },
  { value: "ben", label: "বাংলা" },
  { value: "eng+ben", label: "English + বাংলা" },
];

interface Props {
  settings: ConversionSettings;
  onChange: (settings: ConversionSettings) => void;
  disabled?: boolean;
}

/**
 * Advanced settings, collapsed by default.
 *
 * The defaults are correct for essentially every document, so this stays out
 * of the way. Nothing in here is required to convert a file - OCR in
 * particular is automatic, and a user never needs to know the term.
 */
export function AdvancedOptions({ settings, onChange, disabled = false }: Props) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const modeName = useId();

  const update = <K extends keyof ConversionSettings>(
    key: K,
    value: ConversionSettings[K],
  ) => onChange({ ...settings, [key]: value });

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={panelId}
        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)]"
        style={{ color: "var(--text-secondary)" }}
      >
        <Settings2 size={14} aria-hidden />
        Advanced options
        <ChevronDown
          size={14}
          aria-hidden
          className={cx("transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div
          id={panelId}
          className="mt-3 grid gap-5 rounded-[var(--radius-control)] border p-4 sm:grid-cols-2"
          style={{ background: "var(--surface-sunken)", borderColor: "var(--border)" }}
        >
          <fieldset disabled={disabled}>
            <legend className="text-[12px] font-semibold">Text recognition</legend>
            <p className="mt-0.5 mb-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
              Scanned pages and images are detected automatically.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {OCR_MODES.map((mode) => {
                const active = settings.ocrMode === mode.value;
                return (
                  <label
                    key={mode.value}
                    title={mode.hint}
                    className={cx(
                      "cursor-pointer rounded-md border px-2.5 py-1.5 text-[12px] font-medium transition-colors",
                      !active && "hover:border-[var(--border-strong)]",
                    )}
                    style={{
                      background: active ? "var(--accent-subtle)" : "var(--surface)",
                      borderColor: active ? "var(--accent-border)" : "var(--border)",
                      color: active ? "var(--accent)" : "var(--text-secondary)",
                    }}
                  >
                    <input
                      type="radio"
                      name={modeName}
                      value={mode.value}
                      checked={active}
                      onChange={() => update("ocrMode", mode.value)}
                      className="sr-only"
                    />
                    {mode.label}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <div>
            <label
              htmlFor={`${panelId}-lang`}
              className="text-[12px] font-semibold"
            >
              OCR language
            </label>
            <p className="mt-0.5 mb-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
              Improves accuracy when you know the script.
            </p>
            <select
              id={`${panelId}-lang`}
              value={settings.ocrLanguage}
              disabled={disabled || settings.ocrMode === "off"}
              onChange={(event) =>
                update("ocrLanguage", event.target.value as OcrLanguage)
              }
              className="h-9 w-full rounded-[var(--radius-control)] border px-2.5 text-[13px] disabled:opacity-50"
              style={{
                background: "var(--surface)",
                borderColor: "var(--border)",
                color: "var(--text)",
              }}
            >
              {LANGUAGES.map((language) => (
                <option key={language.value} value={language.value}>
                  {language.label}
                </option>
              ))}
            </select>
          </div>

          <div className="sm:col-span-2">
            <label
              htmlFor={`${panelId}-pages`}
              className="text-[12px] font-semibold"
            >
              Page range
            </label>
            <p className="mt-0.5 mb-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
              PDFs only. Leave empty to convert every page.
            </p>
            <input
              id={`${panelId}-pages`}
              type="text"
              inputMode="numeric"
              value={settings.pageRange}
              disabled={disabled}
              placeholder="e.g. 1-5, 8, 12-14"
              onChange={(event) => update("pageRange", event.target.value)}
              className="h-9 w-full rounded-[var(--radius-control)] border px-2.5 font-mono text-[13px] sm:max-w-xs"
              style={{
                background: "var(--surface)",
                borderColor: "var(--border)",
                color: "var(--text)",
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
