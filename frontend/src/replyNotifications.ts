import type { Conversation } from "./types";

export interface ReplyNotification {
  id: string;
  conversationId: string;
  title: string;
  kind?: "reply" | "report";
}

/** Shared by streamed replies and replies recovered by polling after a reload. */
export class ReplyCompletions {
  private running = new Set<string>();
  private finished = new Set<string>();
  private removed = new Set<string>();
  private away: { start: number; end?: number }[] = [];

  visibility(hidden: boolean, at = Date.now()) {
    const last = this.away.at(-1);
    if (hidden && (!last || last.end !== undefined))
      this.away.push({ start: at });
    if (!hidden && last && last.end === undefined) last.end = at;
  }

  observe(
    conversations: Pick<
      Conversation,
      "id" | "running" | "notification_pending"
    >[],
  ): string[] {
    const completed = conversations
      .filter(
        (c) => !c.running && !c.notification_pending && this.running.has(c.id),
      )
      .map((c) => c.id);
    this.running = new Set(
      conversations
        .filter(
          (c) =>
            (c.running || c.notification_pending) && !this.removed.has(c.id),
        )
        .map((c) => c.id),
    );
    return completed;
  }

  retry(conversationId: string) {
    this.running.add(conversationId);
  }

  finish(
    conversationId: string,
    messageId: string,
    status: string,
    view: { page: string; conversationId: string | null; hidden: boolean },
    completedAt?: string | null,
  ): boolean {
    if (
      !messageId ||
      status === "streaming" ||
      this.removed.has(conversationId) ||
      this.finished.has(messageId)
    )
      return false;
    this.finished.add(messageId);
    const completed = completedAt ? Date.parse(completedAt) : NaN;
    const finishedWhileAway = this.away.some(
      (period) =>
        completed >= period.start && completed <= (period.end ?? Infinity),
    );
    return (
      status === "completed" &&
      (view.hidden ||
        finishedWhileAway ||
        view.page !== "chat" ||
        view.conversationId !== conversationId)
    );
  }

  forget(conversationId: string) {
    this.running.delete(conversationId);
    this.removed.add(conversationId);
  }
}
