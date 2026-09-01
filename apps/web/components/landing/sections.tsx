import {
  Bot,
  Braces,
  Database,
  Download,
  FileSearch,
  FileText,
  FolderArchive,
  Globe,
  Image as ImageIcon,
  Layers,
  Lock,
  NotebookPen,
  ScanText,
  Search,
  Table,
  Upload,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/primitives";
import { CATEGORIES, formatsInCategory } from "@/lib/formats";

function Section({
  id,
  eyebrow,
  title,
  intro,
  children,
}: {
  id: string;
  eyebrow?: string;
  title: string;
  intro?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
      <div className="max-w-2xl">
        {eyebrow && (
          <p
            className="text-[11px] font-semibold tracking-[0.1em] uppercase"
            style={{ color: "var(--accent)" }}
          >
            {eyebrow}
          </p>
        )}
        <h2
          className="mt-3 text-[1.75rem] leading-[1.15] font-semibold tracking-[-0.02em] text-balance sm:text-[2.1rem]"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          {title}
        </h2>
        {intro && (
          <p
            className="mt-4 text-[15px] leading-relaxed text-pretty"
            style={{ color: "var(--text-secondary)" }}
          >
            {intro}
          </p>
        )}
      </div>
      <div className="mt-11">{children}</div>
    </section>
  );
}

function FeatureCard({
  Icon,
  title,
  children,
}: {
  Icon: typeof Bot;
  title: string;
  children: ReactNode;
}) {
  return (
    <Card className="p-6 transition-shadow duration-200 hover:shadow-[var(--shadow-lift)]">
      <span
        className="flex h-10 w-10 items-center justify-center rounded-[12px]"
        style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}
      >
        <Icon size={18} aria-hidden strokeWidth={1.75} />
      </span>
      <h3 className="mt-4 text-[15px] font-semibold tracking-[-0.01em]">{title}</h3>
      <p
        className="mt-2 text-[13.5px] leading-relaxed"
        style={{ color: "var(--text-secondary)" }}
      >
        {children}
      </p>
    </Card>
  );
}

export function WhyMarkdown() {
  return (
    <Section
      id="why-markdown"
      eyebrow="Why Markdown"
      title="Built for the way AI reads information."
      intro="Markdown keeps a document's structure without the markup noise. Headings stay headings and tables stay tables, so a model, a search index, or a person can all follow the same text."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <FeatureCard Icon={Layers} title="Structured">
          Headings, lists and tables survive the conversion, so chunking a
          document for retrieval follows real section boundaries instead of
          arbitrary character counts.
        </FeatureCard>
        <FeatureCard Icon={Search} title="Searchable">
          Plain text indexes cleanly in any search engine or vector store, with
          no binary parsing step in your pipeline.
        </FeatureCard>
        <FeatureCard Icon={FileText} title="Readable">
          The output is legible as-is. You can check what a model will actually
          receive before you send it.
        </FeatureCard>
        <FeatureCard Icon={Wrench} title="Editable">
          Fix a heading or drop a page in the browser before you download.
          It is just text.
        </FeatureCard>
        <FeatureCard Icon={Braces} title="Token-efficient">
          Markdown carries structure in a handful of characters, leaving more of
          a context window for content rather than markup.
        </FeatureCard>
        <FeatureCard Icon={Bot} title="Developer-friendly">
          Diffs in git, renders in every viewer, and needs no special library to
          read back.
        </FeatureCard>
      </div>
    </Section>
  );
}

const USE_CASES = [
  {
    Icon: Database,
    title: "RAG pipelines",
    body: "Feed clean, chunkable text into a vector store without writing a parser for every file type.",
  },
  {
    Icon: Bot,
    title: "AI agents",
    body: "Give an agent documents it can actually read, with structure intact.",
  },
  {
    Icon: NotebookPen,
    title: "Knowledge bases",
    body: "Move legacy Word and PDF material into a docs site or wiki.",
  },
  {
    Icon: Wrench,
    title: "Developer workflows",
    body: "Turn specifications and reports into text that lives in git alongside code.",
  },
  {
    Icon: FileSearch,
    title: "Research",
    body: "Extract readable text from scanned papers and archives, including handwritten-era prints.",
  },
  {
    Icon: Table,
    title: "Data processing",
    body: "Pull spreadsheets and CSVs into Markdown tables for downstream tooling.",
  },
];

export function UseCases() {
  return (
    <Section
      id="use-cases"
      eyebrow="Use cases"
      title="Where clean Markdown pays off."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {USE_CASES.map(({ Icon, title, body }) => (
          <FeatureCard key={title} Icon={Icon} title={title}>
            {body}
          </FeatureCard>
        ))}
      </div>
    </Section>
  );
}

const CATEGORY_ICONS: Record<string, typeof FileText> = {
  documents: FileText,
  data: Table,
  web: Globe,
  technical: NotebookPen,
  images: ImageIcon,
  archives: FolderArchive,
};

export function SupportedFormats() {
  return (
    <Section
      id="formats"
      eyebrow="Formats"
      title="Everything you are likely to have lying around."
      intro="Text-based documents are parsed directly. Scanned pages and images go through OCR automatically, so you do not have to know which is which."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CATEGORIES.map((category) => {
          const Icon = CATEGORY_ICONS[category.id] ?? FileText;
          const formats = formatsInCategory(category.id);
          return (
            <Card key={category.id} className="p-6">
              <div className="flex items-center gap-2.5">
                <Icon
                  size={17}
                  style={{ color: "var(--accent)" }}
                  aria-hidden
                  strokeWidth={1.75}
                />
                <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
                  {category.label}
                </h3>
              </div>
              <p
                className="mt-1.5 text-[13px]"
                style={{ color: "var(--text-secondary)" }}
              >
                {category.description}
              </p>
              <ul className="mt-3.5 flex flex-wrap gap-1.5">
                {formats.map((format) => (
                  <li
                    key={format.extension}
                    className="rounded-[var(--radius-pill)] px-2 py-0.5 font-mono text-[11px]"
                    style={{
                      background: "var(--surface-sunken)",
                      color: "var(--text-muted)",
                    }}
                  >
                    {format.extension}
                  </li>
                ))}
              </ul>
            </Card>
          );
        })}
      </div>
    </Section>
  );
}

const STEPS = [
  {
    Icon: Upload,
    title: "Upload",
    body: "Drop one file or many. Nothing needs configuring, and there is no account to create.",
  },
  {
    Icon: ScanText,
    title: "Convert",
    body: "Each file is identified by its actual contents, then parsed. Pages with no text layer are routed through OCR automatically.",
  },
  {
    Icon: Download,
    title: "Review & download",
    body: "Read the Markdown, edit anything you want to change, then copy it or download a .md file — or a ZIP for a batch.",
  },
];

export function HowItWorks() {
  return (
    <Section id="how-it-works" eyebrow="How it works" title="Three steps, no setup.">
      <ol className="grid gap-4 sm:grid-cols-3">
        {STEPS.map(({ Icon, title, body }, index) => (
          <li key={title}>
            <Card className="h-full p-6">
              <div className="flex items-center gap-3">
                <span
                  className="font-mono text-[12px] font-semibold tracking-widest"
                  style={{ color: "var(--accent)" }}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <Icon size={16} style={{ color: "var(--text-muted)" }} aria-hidden />
              </div>
              <h3 className="mt-4 text-[15px] font-semibold tracking-[-0.01em]">{title}</h3>
              <p
                className="mt-1.5 text-[13px] leading-relaxed"
                style={{ color: "var(--text-secondary)" }}
              >
                {body}
              </p>
            </Card>
          </li>
        ))}
      </ol>
    </Section>
  );
}

export function PrivacySection() {
  return (
    <Section
      id="privacy"
      eyebrow="Privacy"
      title="Your documents aren't our database."
    >
      <Card className="p-6 sm:p-9">
        <div className="flex items-start gap-4">
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-control)]"
            style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}
          >
            <Lock size={18} aria-hidden />
          </span>
          <div className="space-y-3 text-[14px] leading-relaxed">
            <p style={{ color: "var(--text-secondary)" }}>
              Uploads are written to a temporary directory with a random name,
              converted, and then removed. Abandoned sessions expire on a timer
              and a background worker deletes them, so files do not linger if
              you close the tab.
            </p>
            <p style={{ color: "var(--text-secondary)" }}>
              There is no account, no document history, and no database of your
              content. Operational logs record what happened — file type, size,
              duration, success or failure — but never the document text or the
              Markdown produced from it.
            </p>
            <p style={{ color: "var(--text-secondary)" }}>
              Conversion happens on the server, so we are not claiming your
              files are never seen by it. What we can say precisely is that they
              are not stored permanently.{" "}
              <Link
                href="/privacy"
                className="underline underline-offset-2"
                style={{ color: "var(--accent)" }}
              >
                Read the full privacy note
              </Link>
              .
            </p>
          </div>
        </div>
      </Card>
    </Section>
  );
}

const FAQ = [
  {
    q: "Is it free?",
    a: "Yes. There is no charge and no usage tier. Reasonable rate limits apply so the service stays available for everyone.",
  },
  {
    q: "Do I need an account?",
    a: "No. There is no signup, login, or profile. Open the page and drop a file.",
  },
  {
    q: "Are my files stored?",
    a: "Not permanently. Each upload goes into a temporary session directory that is deleted after conversion, when you clear the session, or when the session expires — whichever comes first.",
  },
  {
    q: "Does OCR actually work?",
    a: "Yes, and it runs automatically. When a page has no extractable text, it is rendered and read with Tesseract, then reassembled into headings, paragraphs, lists and tables rather than a flat wall of words.",
  },
  {
    q: "Can it process scanned PDFs?",
    a: "Yes. Scanned PDFs are detected by measuring how much real text each page yields. Pages that come back empty are routed to OCR; pages with a genuine text layer are read directly, which is faster and more accurate.",
  },
  {
    q: "Which languages does OCR support?",
    a: "English and Bengali (বাংলা) are installed, individually or together, and the architecture takes additional Tesseract language packs without code changes.",
  },
  {
    q: "Can it convert Excel workbooks?",
    a: "Yes. Every worksheet becomes its own section with a Markdown table, so a multi-sheet workbook stays navigable.",
  },
  {
    q: "Can I convert multiple files at once?",
    a: "Yes. Drop as many as you like, or upload a ZIP and each supported file inside it is converted separately. Results download individually or together as a ZIP.",
  },
  {
    q: "Can I edit the Markdown before downloading?",
    a: "Yes. The Markdown tab is a real editor with syntax highlighting, search and undo. Your edits are included in whatever you download.",
  },
  {
    q: "Can I use the output for AI and RAG?",
    a: "That is what it is built for. The conversion is faithful — nothing is summarised, rewritten, or invented — so what you feed a model is what the document said.",
  },
  {
    q: "Is this an official Microsoft service?",
    a: "No. It is an independent interface built on the open-source Microsoft MarkItDown library, and is not affiliated with or operated by Microsoft.",
  },
];

export function Faq() {
  return (
    <Section id="faq" eyebrow="FAQ" title="Questions people actually ask.">
      <div className="grid gap-3 lg:grid-cols-2">
        {FAQ.map((item) => (
          <details
            key={item.q}
            className="group rounded-[var(--radius-card)] border p-5 transition-colors"
            style={{
              background: "var(--surface)",
              borderColor: "var(--border)",
              boxShadow: "var(--shadow-soft)",
            }}
          >
            <summary className="cursor-pointer list-none text-[14.5px] font-medium marker:content-['']">
              <span className="flex items-start justify-between gap-3">
                {item.q}
                <span
                  className="mt-0.5 shrink-0 transition-transform group-open:rotate-45"
                  style={{ color: "var(--text-faint)" }}
                  aria-hidden
                >
                  +
                </span>
              </span>
            </summary>
            <p
              className="mt-3 text-[13.5px] leading-relaxed"
              style={{ color: "var(--text-secondary)" }}
            >
              {item.a}
            </p>
          </details>
        ))}
      </div>
    </Section>
  );
}
