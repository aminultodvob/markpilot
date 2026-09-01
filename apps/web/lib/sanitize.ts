/**
 * Markdown rendering and HTML sanitization.
 *
 * Converted Markdown is untrusted. A hostile .docx or .html upload can carry
 * `<script>`, `javascript:` links, event-handler attributes or an inline SVG
 * payload straight through conversion, so the rendered preview is a genuine
 * XSS sink.
 *
 * The pipeline is strictly: parse Markdown -> sanitize the resulting HTML ->
 * only then hand it to the DOM. Raw generated HTML is never inserted
 * unsanitized, and the sanitizer runs on an allowlist so anything unexpected
 * is dropped rather than escaped-and-hoped-for.
 *
 * The Markdown itself is left untouched, because the download must stay a
 * faithful conversion of the source. Safety is applied at render time, which
 * is the only place it is actually needed.
 */

import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({
  gfm: true,
  breaks: false,
});

/** Tags a converted document may legitimately produce. */
const ALLOWED_TAGS = [
  "h1", "h2", "h3", "h4", "h5", "h6",
  "p", "br", "hr", "div", "span",
  "strong", "em", "b", "i", "u", "s", "del", "ins", "mark", "sub", "sup",
  "ul", "ol", "li",
  "blockquote", "pre", "code",
  "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
  "a", "img",
  "dl", "dt", "dd",
  "abbr", "small",
  "input", // GitHub-style task list checkboxes
];

const ALLOWED_ATTR = [
  "href", "title", "alt", "src",
  "colspan", "rowspan", "align",
  "class", "lang", "dir",
  "type", "checked", "disabled",
];

/**
 * Schemes permitted in `href` and `src`.
 *
 * `javascript:`, `vbscript:` and `file:` are absent by construction. `data:`
 * is excluded too: a `data:text/html` URI is a navigation-based XSS vector.
 */
const SAFE_URL = /^(?:https?:|mailto:|tel:|#|\/|\.\/|\.\.\/)/i;

let hooksInstalled = false;

function installHooks(): void {
  if (hooksInstalled) return;
  hooksInstalled = true;

  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.hasAttribute("href")) {
      const href = node.getAttribute("href") ?? "";
      if (!SAFE_URL.test(href.trim())) {
        node.removeAttribute("href");
      } else if (node.tagName === "A") {
        // External links must not be able to reach back via window.opener.
        node.setAttribute("rel", "noopener noreferrer nofollow");
        node.setAttribute("target", "_blank");
      }
    }

    if (node.hasAttribute("src") && !SAFE_URL.test((node.getAttribute("src") ?? "").trim())) {
      node.removeAttribute("src");
    }

    // Task-list checkboxes are the only inputs we keep, and never interactive.
    if (node.tagName === "INPUT") {
      if (node.getAttribute("type") !== "checkbox") {
        node.remove();
      } else {
        node.setAttribute("disabled", "disabled");
      }
    }
  });
}

/** Convert Markdown to HTML that is safe to insert into the document. */
export function renderMarkdown(markdown: string): string {
  installHooks();

  const rawHtml = marked.parse(markdown, { async: false });

  const clean = DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // Belt and braces alongside the allowlist above.
    FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "svg", "math"],
    FORBID_ATTR: ["style", "srcset", "formaction", "onerror", "onload"],
    ALLOW_DATA_ATTR: false,
    USE_PROFILES: { html: true },
  });

  // Wrap tables so a wide one scrolls inside its own box, never the page.
  return clean.replace(
    /<table>/g,
    '<div class="table-scroll"><table>',
  ).replace(/<\/table>/g, "</table></div>");
}

/** True when the Markdown carries HTML a renderer would need to sanitize. */
export function hasRawHtml(markdown: string): boolean {
  return /<\s*(script|iframe|object|embed|svg|form|link|meta|base)\b|\son[a-z]+\s*=|javascript\s*:/i.test(
    markdown,
  );
}
