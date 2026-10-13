import { errorMessage } from "./locale";

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Duka-Request", "1");
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    throw new Error(
      typeof detail === "string"
        ? errorMessage(detail)
        : Array.isArray(detail)
          ? detail.map((x: { msg: string }) => errorMessage(x.msg)).join(" ")
          : `Kërkesa dështoi (${response.status}).`,
    );
  }
  return response.json();
}

export async function streamChat(
  id: string,
  content: string,
  model: string,
  onEvent: (event: Record<string, string>) => void,
) {
  const response = await fetch(`/api/conversations/${id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Duka-Request": "1" },
    credentials: "same-origin",
    body: JSON.stringify({ content, model: model || null }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(
      typeof payload.detail === "string"
        ? errorMessage(payload.detail)
        : "Mesazhi nuk mund të dërgohet.",
    );
  }
  const reader = response.body?.getReader();
  if (!reader)
    throw new Error("Ky shfletues nuk mbështet përgjigjet e drejtpërdrejta.");
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "done" || event.type === "error") terminal = true;
        onEvent(event);
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const event = JSON.parse(buffer);
      terminal ||= ["done", "error"].includes(event.type);
      onEvent(event);
    }
    if (!terminal)
      throw new Error(
        "Lidhja u ndërpre para përfundimit të përgjigjes. Provoni përsëri.",
      );
  } finally {
    reader.releaseLock();
  }
}
