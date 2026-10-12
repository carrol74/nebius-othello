import { NextRequest, NextResponse } from "next/server";
import { attachSession, sessionId } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  return attachSession(NextResponse.json({ ready: true }, { headers: { "Cache-Control": "no-store" } }), sessionId(request));
}
