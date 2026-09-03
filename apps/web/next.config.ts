import type { NextConfig } from "next";

/*
 * Two deployment shapes are supported, and they need different output modes:
 *
 * 1. Vercel (or any managed Next host). Each route becomes a serverless
 *    function. `output: "standalone"` must NOT be set here - it produces a
 *    self-contained server bundle instead of per-route functions, and the
 *    result is that dynamic routes 404 while static pages still serve. That is
 *    exactly the failure it caused on Vercel.
 *
 * 2. Docker / self-hosting. Here `output: "standalone"` is what we want, so
 *    the runtime image carries no node_modules.
 *
 * Vercel sets the `VERCEL` env var on every build, so the mode is detected
 * rather than configured.
 */
const isVercel = Boolean(process.env.VERCEL);
const isStandalone = process.env.NEXT_OUTPUT_STANDALONE === "true" && !isVercel;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,

  ...(isStandalone
    ? {
        output: "standalone" as const,
        // The formats registry lives outside apps/web, so tracing has to start
        // at the repo root. Only meaningful for the standalone bundle.
        outputFileTracingRoot: process.cwd() + "/../..",
      }
    : {}),

  // NOTE: `env` is deliberately not used for CONVERTER_API_URL. Values there
  // are inlined at build time, which would bake in whatever the URL was when
  // the bundle was built (in practice `http://localhost:8000`). The proxy
  // route reads process.env at request time instead.

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
