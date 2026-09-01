import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono, Newsreader } from "next/font/google";

import { SiteFooter } from "@/components/landing/SiteFooter";
import { SiteHeader } from "@/components/landing/SiteHeader";
import { THEME_INIT_SCRIPT, ThemeProvider } from "@/components/theme/ThemeProvider";

import "./globals.css";

/*
 * Fonts are self-hosted at build time by next/font, so there is no request to
 * Google at runtime and no layout shift from a late-arriving face.
 *
 * Newsreader is the reading face: a warm text serif designed for screens,
 * which is what the result view is actually for.
 */
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const newsreader = Newsreader({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-serif-display",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500"],
  variable: "--font-mono-code",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

const TITLE = "MarkPilot — Convert PDF, Word & Excel to Markdown";
const DESCRIPTION =
  "Convert PDF, Word, PowerPoint, Excel, images, HTML, CSV, JSON and more " +
  "into clean Markdown for AI workflows. Scanned documents are read with OCR.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s — MarkPilot",
  },
  description: DESCRIPTION,
  applicationName: "MarkPilot",
  keywords: [
    "markdown converter",
    "pdf to markdown",
    "docx to markdown",
    "excel to markdown",
    "OCR to markdown",
    "scanned pdf to markdown",
    "RAG pipeline",
    "AI document processing",
  ],
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "MarkPilot",
    title: TITLE,
    description: DESCRIPTION,
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfaf8" },
    { media: "(prefers-color-scheme: dark)", color: "#171614" },
  ],
};

const STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "MarkPilot",
  url: SITE_URL,
  applicationCategory: "DeveloperApplication",
  operatingSystem: "Any",
  description: DESCRIPTION,
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  featureList: [
    "Convert PDF, Word, PowerPoint and Excel to Markdown",
    "OCR for scanned documents and images",
    "English and Bengali text recognition",
    "Batch conversion with ZIP download",
    "No account required",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${newsreader.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        {/* Applies the theme class before first paint, so there is no flash. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
        />
      </head>
      <body className="min-h-screen antialiased">
        <ThemeProvider>
          <a
            href="#converter"
            className="sr-only rounded-lg focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:px-4 focus:py-2 focus:text-sm focus:font-medium"
            style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
          >
            Skip to converter
          </a>
          <div className="flex min-h-screen flex-col">
            <SiteHeader />
            <main className="flex-1">{children}</main>
            <SiteFooter />
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
