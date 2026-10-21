// Calls to the copilot app's own API. The Apps ingress signs the browser in and forwards the visitor's token, so
// every request here runs as them; nothing in the page holds a credential.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(url: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(url, { credentials: "same-origin", ...init });
  const text = await resp.text();
  let body: any = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text };
  }
  if (!resp.ok) {
    const err = body.error ?? body.detail ?? text;
    throw new ApiError(resp.status, typeof err === "string" ? err : (err?.message ?? JSON.stringify(err)));
  }
  return body as T;
}

export function post<T>(url: string, data: unknown, headers: Record<string, string> = {}): Promise<T> {
  return api<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(data),
  });
}

export function problem(e: unknown): string {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403))
    return "Your sign-in has expired or was refused. Reload the page to sign in again.";
  if (e instanceof ApiError) return `${e.status}: ${e.message}`;
  return e instanceof Error ? e.message : String(e);
}

/** Read a server-sent event stream, calling onEvent for each event; returns the last event id seen. */
export async function readSSE(
  resp: Response,
  onEvent: (name: string, data: any) => void,
  after?: number,
): Promise<number | undefined> {
  let last = after;
  if (!resp.body) return last;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let name = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
        else if (line.startsWith("id: ")) last = Number(line.slice(4));
      }
      if (!data) continue;
      try {
        onEvent(name, JSON.parse(data));
      } catch {
        /* a malformed event is skipped */
      }
    }
  }
  return last;
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
