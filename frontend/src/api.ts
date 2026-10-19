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
  attachmentIds: string[] = [],
  options: {
    request_id?: string;
    reasoning_effort?: string | null;
    retry_message_id?: string | null;
    interrupt_current?: boolean;
  } = {},
  signal?: AbortSignal,
) {
  const requestId = options.request_id || crypto.randomUUID();
  let runId = "";
  let after = 0;
  let terminal = false;
  let first = true;
  let reconnects = 0;
  while (!terminal) {
    signal?.throwIfAborted();
    try {
      const response = await fetch(
        first
          ? `/api/conversations/${id}/messages`
          : `/api/conversations/${id}/runs/${runId}/events?after=${after}`,
        {
          method: first ? "POST" : "GET",
          headers: {
            "Content-Type": "application/json",
            "X-Duka-Request": "1",
          },
          credentials: "same-origin",
          signal,
          ...(first
            ? {
                body: JSON.stringify({
                  content,
                  model: model || null,
                  attachment_ids: attachmentIds,
                  request_id: requestId,
                  ...options,
                }),
              }
            : {}),
        },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        terminal =
          response.status < 500 && !(response.status === 409 && reconnects > 0);
        throw new Error(
          typeof payload.detail === "string"
            ? errorMessage(payload.detail)
            : "Mesazhi nuk mund të dërgohet.",
        );
      }
      first = false;
      const reader = response.body?.getReader();
      if (!reader) {
        terminal = true;
        throw new Error(
          "Ky shfletues nuk mbështet përgjigjet e drejtpërdrejta.",
        );
      }
      const decoder = new TextDecoder();
      let buffer = "";
      const deliver = (line: string) => {
        if (!line.trim()) return;
        const event = JSON.parse(line);
        if (event.type === "message") runId = event.id;
        if (event.seq) after = Number(event.seq);
        if (["done", "error"].includes(event.type)) terminal = true;
        onEvent(event);
      };
      try {
        while (true) {
          const { done, value } = await reader.read();
          buffer += done
            ? decoder.decode()
            : decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          lines.forEach(deliver);
          if (done) break;
        }
        if (buffer.trim()) deliver(buffer);
      } finally {
        reader.releaseLock();
      }
      if (!terminal) throw new Error("Lidhja u ndërpre.");
    } catch (e) {
      if (signal?.aborted) throw e;
      if (terminal) throw e;
      // A persistent request key identifies this exact submission after a lost response.
      // Retrying its POST is idempotent; it cannot create a second user message.
      onEvent({ type: "reconnecting" });
      await new Promise((resolve) =>
        setTimeout(resolve, Math.min(5000, 500 * ++reconnects)),
      );
      signal?.throwIfAborted();
      if (!runId) {
        try {
          const accepted = await api<{ run_id: string }>(
            `/conversations/${id}/requests/${requestId}`,
          );
          runId = accepted.run_id;
        } catch {
          first = true;
          continue;
        }
      }
      first = false;
    }
  }
}
