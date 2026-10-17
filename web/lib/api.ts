import type { ApiFailure } from "./types";

const pendingWrites = new Map<string, string>();

export class ApiError extends Error {
  constructor(public status: number, public detail: ApiFailure) {
    super(detail.message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  let requestBody = body;
  let pendingKey: string | undefined;
  if (body && "request_id" in body && typeof body.request_id === "string" && !path.endsWith("/ai-move")) {
    const { request_id, ...inputs } = body;
    pendingKey = `${path}:${JSON.stringify(inputs)}`;
    const stableId = pendingWrites.get(pendingKey) ?? request_id;
    pendingWrites.set(pendingKey, stableId);
    requestBody = { ...inputs, request_id: stableId };
  }
  const headers = new Headers();
  if (requestBody !== undefined) headers.set("Content-Type", "application/json");
  if (requestBody && "request_id" in requestBody && typeof requestBody.request_id === "string") headers.set("X-Request-ID", requestBody.request_id);
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
    cache: "no-store",
    signal,
  });
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new ApiError(response.status, { code: "INVALID_RESPONSE", message: "The service returned an unreadable response. Contact the maintainer." });
  }
  const payload: unknown = await response.json();
  if (!response.ok) {
    const error = payload as { detail?: ApiFailure } & Partial<ApiFailure>;
    const detail = error.detail ?? error;
    if (pendingKey && response.status < 500 && detail.code !== "INVALID_RESPONSE") pendingWrites.delete(pendingKey);
    throw new ApiError(response.status, {
      code: detail.code ?? "REQUEST_FAILED",
      message: detail.message ?? `Request failed (${response.status})`,
      request_id: detail.request_id,
      retryable: detail.retryable,
    });
  }
  if (pendingKey) pendingWrites.delete(pendingKey);
  return payload as T;
}

export function requestId() {
  return crypto.randomUUID();
}
