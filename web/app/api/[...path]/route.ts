import { NextRequest, NextResponse } from "next/server";
import { attachSession, sessionId } from "@/lib/session";
import { sameOrigin } from "@/lib/request-origin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const id = "[A-Za-z0-9_-]{1,100}";
const endpoints: Record<string, RegExp[]> = {
  GET: [/^games$/, new RegExp(`^games/${id}$`), new RegExp(`^games/${id}/review(/lesson)?$`), new RegExp(`^games/${id}/lessons(/compare|/practice|/earlier)?$`), new RegExp(`^tasks/${id}$`)],
  POST: [
    /^games$/,
    new RegExp(`^games/${id}/(moves|ai-move|hint|hint-displays|reviews|branches|lessons)$`),
    new RegExp(`^games/${id}/review/questions$`),
    new RegExp(`^games/${id}/lessons/practice$`),
  ],
};

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!endpoints[request.method]?.some((pattern) => pattern.test(path))) {
    return NextResponse.json({ code: "NOT_FOUND", message: "Endpoint not found" }, { status: 404 });
  }
  const origin = request.headers.get("origin");
  // NextURL normalizes loopback IPs to localhost; Host retains the browser's authority.
  if (request.method === "POST"
    && !sameOrigin(origin, request.headers.get("host"), request.nextUrl.protocol)) {
    return NextResponse.json({ code: "INVALID_ORIGIN", message: "Request origin does not match" }, { status: 403 });
  }
  const backendUrl = process.env.BACKEND_URL;
  const serviceToken = process.env.BACKEND_SERVICE_TOKEN;
  if (!backendUrl || !serviceToken) {
    return NextResponse.json({ code: "BACKEND_NOT_CONFIGURED", message: "Service is not configured. Contact the project maintainer." }, { status: 503 });
  }
  const session = sessionId(request);
  const trace = request.headers.get("x-request-id");
  let body: string | undefined;
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.startsWith("application/json")) {
      return NextResponse.json({ code: "INVALID_CONTENT_TYPE", message: "Request must use JSON" }, { status: 415 });
    }
    if (Number(request.headers.get("content-length")) > 16_384) {
      return NextResponse.json({ code: "BODY_TOO_LARGE", message: "Request body is too large" }, { status: 413 });
    }
    body = await request.text();
    if (new TextEncoder().encode(body).length > 16_384) {
      return NextResponse.json({ code: "BODY_TOO_LARGE", message: "Request body is too large" }, { status: 413 });
    }
  }
  try {
    const upstream = await fetch(`${backendUrl.replace(/\/$/, "")}/${path}${request.nextUrl.search}`, {
      method: request.method,
      headers: {
        Authorization: `Bearer ${serviceToken}`,
        "X-Session-ID": session,
        "Content-Type": "application/json",
        ...(trace && /^[A-Za-z0-9:_-]{8,100}$/.test(trace) ? { "X-Request-ID": trace } : {}),
      },
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(240_000),
    });
    const response = new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
    return attachSession(response, session);
  } catch (error) {
    console.error("Backend request failed", { path, error });
    return attachSession(NextResponse.json({ code: "BACKEND_UNAVAILABLE", message: "Could not connect to the service. Please try again.", retryable: true }, { status: 502 }), session);
  }
}

export const GET = forward;
export const POST = forward;
