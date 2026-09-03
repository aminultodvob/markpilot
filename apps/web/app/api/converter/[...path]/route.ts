/**
 * Reverse proxy to the converter service.
 *
 * The browser talks only to this app. The converter runs on the internal
 * network with no public port, so its address never appears in client code and
 * it cannot be reached directly.
 *
 * The proxy is intentionally narrow: it forwards only known API paths, only
 * the headers the converter needs, and streams bodies rather than buffering
 * them, so a 50 MB upload does not become 50 MB of Node heap.
 */

import { NextRequest } from "next/server";

const CONVERTER_URL = process.env.CONVERTER_API_URL ?? "http://localhost:8000";

/** Paths this proxy is willing to forward. Anything else is refused. */
const ALLOWED_PREFIXES = ["api/v1/", "health", "ready"];

/** Request headers forwarded upstream. Everything else is dropped. */
const FORWARD_REQUEST_HEADERS = [
  "content-type",
  "content-length",
  "accept",
  "x-session-id",
  "x-session-token",
];

/** Response headers passed back to the browser. */
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "content-length",
  "retry-after",
  "x-content-type-options",
];

export const dynamic = "force-dynamic";
// Node runtime: streaming request bodies to an internal service.
export const runtime = "nodejs";
/*
 * A converter on a free hosting tier is suspended when idle and cold-starts on
 * the next request, which can take ~35s. The platform default of 10s would
 * abort that as a gateway error, so this is raised to the maximum the plan
 * allows. Note that managed hosts also cap the *request body* of a function
 * (4.5 MB on Vercel), which no timeout can work around - see lib/api.ts for
 * the direct-upload mode that exists for exactly that reason.
 */
export const maxDuration = 60;

function isAllowed(path: string): boolean {
  return ALLOWED_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix));
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  const joined = path.join("/");

  if (!isAllowed(joined)) {
    return Response.json(
      { error: { code: "not_found", message: "Unknown endpoint." } },
      { status: 404 },
    );
  }

  const target = new URL(`/${joined}`, CONVERTER_URL);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const hasBody = request.method !== "GET" && request.method !== "DELETE";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Required by undici when streaming a request body.
      ...(hasBody ? { duplex: "half" } : {}),
      cache: "no-store",
      redirect: "manual",
    } as RequestInit);
  } catch {
    return Response.json(
      {
        error: {
          code: "converter_unavailable",
          message:
            "The conversion service is unavailable. Please try again shortly.",
        },
      },
      { status: 503 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  responseHeaders.set("Cache-Control", "no-store");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
