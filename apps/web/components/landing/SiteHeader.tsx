import Link from "next/link";

import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Wordmark } from "@/components/ui/Logo";

const NAV = [
  { href: "#converter", label: "Convert" },
  { href: "#formats", label: "Formats" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#faq", label: "FAQ" },
];

export function SiteHeader() {
  return (
    <header
      className="sticky top-0 z-40 border-b backdrop-blur-xl"
      style={{
        borderColor: "var(--border)",
        background: "color-mix(in srgb, var(--bg) 82%, transparent)",
      }}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="rounded-lg" aria-label="MarkPilot home">
          <Wordmark />
        </Link>

        <nav aria-label="Sections" className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="rounded-lg px-3 py-1.5 text-[13.5px] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
              style={{ color: "var(--text-secondary)" }}
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <a
            href="https://github.com/microsoft/markitdown"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden rounded-lg px-3 py-1.5 text-[13.5px] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] sm:block"
            style={{ color: "var(--text-secondary)" }}
          >
            GitHub
          </a>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
