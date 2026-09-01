import Link from "next/link";

import { Wordmark } from "@/components/ui/Logo";

const PRODUCT = [
  { href: "#converter", label: "Converter" },
  { href: "#formats", label: "Supported formats" },
  { href: "#faq", label: "FAQ" },
];

export function SiteFooter() {
  return (
    <footer
      className="border-t"
      style={{ borderColor: "var(--border)", background: "var(--bg-subtle)" }}
    >
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <div className="flex flex-col gap-10 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-sm">
            <Wordmark size={24} />
            <p
              className="mt-4 text-[13.5px] leading-relaxed"
              style={{ color: "var(--text-muted)" }}
            >
              Turn documents into AI-ready Markdown. Files are processed
              temporarily for conversion and are not stored permanently.
            </p>
          </div>

          <div className="flex gap-14">
            <nav aria-label="Product">
              <h2
                className="text-[11px] font-semibold tracking-[0.08em] uppercase"
                style={{ color: "var(--text-faint)" }}
              >
                Product
              </h2>
              <ul className="mt-4 space-y-1 text-[13.5px]">
                {PRODUCT.map((item) => (
                  <li key={item.href}>
                    <a
                      href={item.href}
                      className="inline-flex min-h-[26px] items-center transition-colors hover:text-[var(--text)]"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>

            <nav aria-label="Details">
              <h2
                className="text-[11px] font-semibold tracking-[0.08em] uppercase"
                style={{ color: "var(--text-faint)" }}
              >
                Details
              </h2>
              <ul className="mt-4 space-y-1 text-[13.5px]">
                <li>
                  <Link
                    href="/privacy"
                    className="inline-flex min-h-[26px] items-center transition-colors hover:text-[var(--text)]"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    Privacy
                  </Link>
                </li>
                <li>
                  <a
                    href="https://github.com/microsoft/markitdown"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-[26px] items-center transition-colors hover:text-[var(--text)]"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    Microsoft MarkItDown
                  </a>
                </li>
                <li>
                  <a
                    href="https://github.com/tesseract-ocr/tesseract"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-[26px] items-center transition-colors hover:text-[var(--text)]"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    Tesseract OCR
                  </a>
                </li>
              </ul>
            </nav>
          </div>
        </div>

        <div
          className="mt-10 border-t pt-6 text-[12px] leading-relaxed"
          style={{ borderColor: "var(--border)", color: "var(--text-faint)" }}
        >
          <p>
            MarkPilot is an independent interface built on the open-source{" "}
            <a
              href="https://github.com/microsoft/markitdown"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
              style={{ color: "var(--text-muted)" }}
            >
              Microsoft MarkItDown
            </a>{" "}
            library (MIT licensed). It is not affiliated with, endorsed by, or
            operated by Microsoft.
          </p>
        </div>
      </div>
    </footer>
  );
}
