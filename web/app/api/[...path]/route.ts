import { NextRequest, NextResponse } from "next/server";
import { attachSession, sessionId } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const id = "[A-Za-z0-9_-]{1,100}";
const endpoints: Record<string, RegExp[]> = {
  GET: [new RegExp(`^games/${id}$`), new RegExp(`^games/${id}/review$`), new RegExp(`^tasks/${id}$`)],
  POST: [
    /^games$/,
    new RegExp(`^games/${id}/(moves|ai-move|hint|hint-displays|reviews|branches)$`),
    new RegExp(`^games/${id}/review/questions$`),
  ],
};

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!endpoints[request.method]?.some((pattern) => pattern.test(path))) {
    return NextResponse.json({ code: "NOT_FOUND", message: "接口不存在" }, { status: 404 });
  }
  const origin = request.headers.get("origin");
  if (request.method === "POST" && origin !== request.nextUrl.origin) {
    return NextResponse.json({ code: "INVALID_ORIGIN", message: "请求来源不匹配" }, { status: 403 });
  }
  const backendUrl = process.env.BACKEND_URL;
  const serviceToken = process.env.BACKEND_SERVICE_TOKEN;
  if (!backendUrl || !serviceToken) {
    return NextResponse.json({ code: "BACKEND_NOT_CONFIGURED", message: "服务尚未配置，请联系项目维护者" }, { status: 503 });
  }
  const session = sessionId(request);
  const trace = request.headers.get("x-request-id");
  let body: string | undefined;
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.startsWith("application/json")) {
      return NextResponse.json({ code: "INVALID_CONTENT_TYPE", message: "请求必须使用 JSON 格式" }, { status: 415 });
    }
    if (Number(request.headers.get("content-length")) > 16_384) {
      return NextResponse.json({ code: "BODY_TOO_LARGE", message: "请求内容过长" }, { status: 413 });
    }
    body = await request.text();
    if (new TextEncoder().encode(body).length > 16_384) {
      return NextResponse.json({ code: "BODY_TOO_LARGE", message: "请求内容过长" }, { status: 413 });
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
    return attachSession(NextResponse.json({ code: "BACKEND_UNAVAILABLE", message: "连接服务失败，请重试", retryable: true }, { status: 502 }), session);
  }
}

export const GET = forward;
export const POST = forward;
