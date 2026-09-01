/**
 * Supported formats, read from the shared registry.
 *
 * `packages/formats/formats.json` is the single source of truth, consumed by
 * both this app and the Python converter service. Adding a format is one edit
 * there, not one edit per codebase.
 */

import registry from "@formats/formats.json";

export interface SupportedFormat {
  extension: string;
  label: string;
  category: string;
  icon: string;
  mimeTypes: string[];
  ocrCapable: boolean;
}

export interface FormatCategory {
  id: string;
  label: string;
  description: string;
}

export const CATEGORIES: FormatCategory[] = registry.categories;

export const FORMATS: SupportedFormat[] = registry.formats.map((format) => ({
  extension: format.extension,
  label: format.label,
  category: format.category,
  icon: format.icon,
  mimeTypes: format.mimeTypes,
  ocrCapable: format.ocrCapable,
}));

const BY_EXTENSION = new Map(FORMATS.map((f) => [f.extension, f]));

/** Every accepted extension, for the file input's `accept` attribute. */
export const ACCEPT_ATTRIBUTE = FORMATS.map((f) => f.extension).join(",");

/** Extensions shown in the dropzone hint, in a deliberate order. */
export const HEADLINE_FORMATS = [
  "PDF",
  "DOCX",
  "PPTX",
  "XLSX",
  "Images",
  "More",
];

export function extensionOf(filename: string): string {
  const index = filename.lastIndexOf(".");
  return index === -1 ? "" : filename.slice(index).toLowerCase();
}

export function formatFor(filename: string): SupportedFormat | undefined {
  return BY_EXTENSION.get(extensionOf(filename));
}

export function isSupported(filename: string): boolean {
  return BY_EXTENSION.has(extensionOf(filename));
}

/** Short badge label for a file row, e.g. "PDF", "DOCX". */
export function badgeFor(filename: string): string {
  const extension = extensionOf(filename);
  return extension ? extension.slice(1).toUpperCase() : "FILE";
}

export function formatsInCategory(categoryId: string): SupportedFormat[] {
  // De-duplicated by label so ".jpg"/".jpeg" and ".html"/".htm" appear once.
  const seen = new Set<string>();
  return FORMATS.filter((format) => {
    if (format.category !== categoryId) return false;
    if (seen.has(format.label)) return false;
    seen.add(format.label);
    return true;
  });
}
