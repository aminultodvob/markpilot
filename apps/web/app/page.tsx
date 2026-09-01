import { Converter } from "@/components/converter/Converter";
import {
  Faq,
  HowItWorks,
  PrivacySection,
  SupportedFormats,
  UseCases,
  WhyMarkdown,
} from "@/components/landing/sections";

export default function HomePage() {
  return (
    <>
      {/*
        Hero and converter share one screen. The headline sets context in a
        sentence and the dropzone sits directly beneath it, so the primary
        action is never pushed below the fold.
      */}
      <section
        id="converter"
        className="aurora relative border-b"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="mx-auto max-w-3xl px-4 pt-14 pb-20 sm:px-6 sm:pt-20">
          <div className="text-center">
            <span
              className="inline-flex items-center gap-2 rounded-[var(--radius-pill)] border px-3 py-1 text-[12px] font-medium"
              style={{
                background: "var(--surface)",
                borderColor: "var(--border)",
                color: "var(--text-muted)",
                boxShadow: "var(--shadow-soft)",
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: "var(--accent)" }}
                aria-hidden
              />
              Built on Microsoft MarkItDown · OCR included
            </span>

            <h1
              className="mt-6 text-4xl leading-[1.08] font-semibold tracking-[-0.025em] text-balance sm:text-[3.4rem]"
              style={{ fontFamily: "var(--font-serif)" }}
            >
              Turn documents into
              <br className="hidden sm:block" />{" "}
              <span style={{ color: "var(--accent)" }}>AI-ready Markdown.</span>
            </h1>

            <p
              className="mx-auto mt-5 max-w-xl text-[15.5px] leading-relaxed text-pretty"
              style={{ color: "var(--text-secondary)" }}
            >
              Convert PDF, Word, PowerPoint, Excel, images, and structured files
              into clean Markdown for AI workflows, RAG pipelines, knowledge
              bases, and developer tools.
            </p>
          </div>

          <div className="mt-10">
            <Converter />
          </div>
        </div>
      </section>

      <WhyMarkdown />
      <div style={{ background: "var(--bg-subtle)" }}>
        <UseCases />
      </div>
      <SupportedFormats />
      <div style={{ background: "var(--bg-subtle)" }}>
        <HowItWorks />
      </div>
      <PrivacySection />
      <div style={{ background: "var(--bg-subtle)" }}>
        <Faq />
      </div>
    </>
  );
}
