import { randomUUID } from "node:crypto";
import type { NextRequest, NextResponse } from "next/server";

const cookieName = "nemothello_session";

export function sessionId(request: NextRequest) {
  const existing = request.cookies.get(cookieName)?.value;
  return existing && /^[a-f0-9-]{36}$/.test(existing) ? existing : randomUUID();
}

export function attachSession(response: NextResponse, session: string) {
  response.cookies.set(cookieName, session, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return response;
}
