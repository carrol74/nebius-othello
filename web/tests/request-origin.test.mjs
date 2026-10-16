import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server.js";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../lib/request-origin.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { sameOrigin } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("NextRequest loopback normalization does not reject the real browser origin", () => {
  const request = new NextRequest("http://127.0.0.1:3017/api/games", {
    headers: { host: "127.0.0.1:3017", origin: "http://127.0.0.1:3017" },
  });
  assert.equal(request.nextUrl.origin, "http://localhost:3017");
  assert.equal(sameOrigin(request.headers.get("origin"), request.headers.get("host"),
    request.nextUrl.protocol), true);
});

test("same origin includes host, protocol, and port", () => {
  assert.equal(sameOrigin("https://example.com", "example.com", "https:"), true);
  assert.equal(sameOrigin("https://example.com", "EXAMPLE.COM:443", "https:"), true);
  assert.equal(sameOrigin("http://[::1]:3017", "[::1]:3017", "http:"), true);
  for (const [origin, host, protocol] of [
    ["http://localhost:3017", "127.0.0.1:3017", "http:"],
    ["https://evil.example", "example.com", "https:"],
    ["http://example.com", "example.com", "https:"],
    ["https://example.com:8443", "example.com", "https:"],
    ["https://example.com.evil.example", "example.com", "https:"],
  ]) assert.equal(sameOrigin(origin, host, protocol), false);
});

test("missing, opaque, malformed, and non-origin values are rejected", () => {
  for (const [origin, host, protocol] of [
    [null, "example.com", "https:"],
    ["null", "example.com", "https:"],
    ["https://example.com/path", "example.com", "https:"],
    ["https://example.com", null, "https:"],
    ["https://example.com", "user@example.com", "https:"],
    ["https://example.com", "example.com/path", "https:"],
    ["https://example.com", "example.com", "file:"],
  ]) assert.equal(sameOrigin(origin, host, protocol), false);
});
