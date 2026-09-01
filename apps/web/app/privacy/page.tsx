import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "How MarkPilot handles uploaded documents: temporary processing, "
    + "automatic cleanup, what is logged, and what is not.",
  alternates: { canonical: "/privacy" },
};

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="mt-11 mb-3 text-[1.3rem] font-semibold tracking-[-0.015em]"
      style={{ fontFamily: "var(--font-serif)" }}
    >
      {children}
    </h2>
  );
}

export default function PrivacyPage() {
  return (
    <article className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
      <h1
        className="text-[2.4rem] font-semibold tracking-[-0.025em]"
        style={{ fontFamily: "var(--font-serif)" }}
      >
        Privacy
      </h1>
      <p className="mt-3 text-[15px]" style={{ color: "var(--text-muted)" }}>
        What happens to a document you upload, described precisely.
      </p>

      <div
        className="mt-8 space-y-4 text-[15px] leading-relaxed"
        style={{ color: "var(--text-secondary)" }}
      >
        <Heading>Temporary processing</Heading>
        <p>
          Converting a document requires reading it, so your file is uploaded to
          our server and processed there. It is written to a directory named
          with a cryptographically random identifier, inside a temporary area
          that is not reachable from the web.
        </p>
        <p>
          We do not claim that your files are never seen by our systems — they
          are, because that is how conversion works. What we can state precisely
          is that they are not stored permanently, are not indexed, are not
          shared, and are not used to train anything.
        </p>

        <Heading>Cleanup</Heading>
        <p>An uploaded file is removed at the earliest of these points:</p>
        <ul className="ml-5 list-disc space-y-1.5">
          <li>immediately after it converts successfully;</li>
          <li>when you press <strong>Clear</strong>, which deletes the whole session;</li>
          <li>when you close the tab, which signals the server to release the session;</li>
          <li>when the session expires — 30 minutes by default;</li>
          <li>
            when the service restarts, since results are held in memory and
            leftover directories are swept on startup.
          </li>
        </ul>
        <p>
          A background worker runs continuously to delete expired sessions, so
          cleanup does not depend on you coming back.
        </p>

        <Heading>No account, no history</Heading>
        <p>
          There is no signup, no login, and no user profile. Nothing links one
          conversion to another, and there is no document history to browse
          because none is kept. A session is a random identifier plus a bearer
          token held in your browser tab; refreshing the page discards it.
        </p>

        <Heading>What we log</Heading>
        <p>
          Operational logs record the shape of the work, never its content:
          format, file size, duration, success or failure, error category, and
          whether OCR ran. Document text, the Markdown produced from it, and
          full filenames are never written to logs.
        </p>

        <Heading>Analytics</Heading>
        <p>
          There is no third-party analytics, no advertising network, and no
          cross-site tracking. The only thing stored in your browser is your
          light/dark theme preference.
        </p>

        <Heading>Third-party services</Heading>
        <p>
          In the default configuration, conversion and OCR run entirely on our
          own server using Microsoft MarkItDown and Tesseract. Your documents
          are not sent to any third-party API.
        </p>
        <p>
          The software supports an optional vision-model OCR provider, which
          would send page images to an external service. It is disabled unless
          an operator explicitly configures it. If you are running this yourself
          and enable it, that choice — and the third party&rsquo;s handling of
          your data — is yours to disclose.
        </p>

        <Heading>Open source</Heading>
        <p>
          Conversion is powered by{" "}
          <a
            href="https://github.com/microsoft/markitdown"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--accent)" }}
          >
            Microsoft MarkItDown
          </a>{" "}
          (MIT) and{" "}
          <a
            href="https://github.com/tesseract-ocr/tesseract"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--accent)" }}
          >
            Tesseract OCR
          </a>{" "}
          (Apache-2.0). MarkPilot is an independent interface built on
          them and is not affiliated with, endorsed by, or operated by
          Microsoft.
        </p>
      </div>

      <p className="mt-12">
        <Link
          href="/"
          className="text-[14px] underline underline-offset-2"
          style={{ color: "var(--accent)" }}
        >
          ← Back to the converter
        </Link>
      </p>
    </article>
  );
}
