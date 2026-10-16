import type { Message, Report } from "./types";

// Streams continue when the user opens a different conversation. Their output
// stays keyed by the originating conversation rather than the current page.
export class ConversationRuns {
  private runs = new Map<string, { messages: Message[]; activity: string }>();
  get size() {
    return this.runs.size;
  }
  has(id: string | null) {
    return !!id && this.runs.has(id);
  }
  snapshot(id: string) {
    return this.runs.get(id)?.messages;
  }
  activity(id: string | null) {
    return id ? this.runs.get(id)?.activity || "" : "";
  }
  start(id: string, messages: Message[]) {
    if (this.runs.has(id))
      throw new Error("A response is already running in this conversation.");
    this.runs.set(id, { messages, activity: "Duke menduar" });
  }
  update(id: string, content: string, status: string, activity?: string) {
    const run = this.runs.get(id);
    if (!run) return;
    if (activity) run.activity = activity;
    run.messages = run.messages.map((m) =>
      m.id === "streaming" ? { ...m, content, status } : m,
    );
    return run.messages;
  }
  finish(id: string) {
    this.runs.delete(id);
  }
}

export function runningReports(
  reports: Report[],
  conversationId: string | null,
) {
  if (!conversationId) return [];
  return reports.filter(
    (r) =>
      r.conversation_id === conversationId &&
      ["queued", "running"].includes(r.status),
  );
}

/** Keep the current assistant's dots visible through the associated Excel work. */
export function pendingAssistantMessages(
  messages: Message[],
  reports: Report[],
  conversationId: string | null,
) {
  const assistants = messages.filter((m) => m.role === "assistant");
  const pending = new Set(
    assistants.filter((m) => m.status === "streaming").map((m) => m.id),
  );
  if (runningReports(reports, conversationId).length) {
    const latest = assistants.at(-1);
    if (latest) pending.add(latest.id);
  }
  return pending;
}

/** Replaying an earlier user message drops its old answer and all later turns. */
export function messagesBeforeRestart(
  messages: Message[],
  messageId: string,
): Message[] {
  const index = messages.findIndex(
    (m) => m.id === messageId && m.role === "user",
  );
  if (index < 0) throw new Error("Mesazhi nuk u gjet në këtë bisedë.");
  return messages.slice(0, index);
}
