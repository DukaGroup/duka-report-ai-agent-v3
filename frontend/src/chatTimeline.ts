import type { Message, Report } from "./types";

type ChatEntry =
  | { kind: "message"; key: string; message: Message }
  | { kind: "report"; key: string; report: Report };

/** Keep report cards at their creation point rather than after every new message. */
export function buildChatTimeline(
  messages: Message[],
  reports: Report[],
): ChatEntry[] {
  const entries: ChatEntry[] = [
    ...messages.map(
      (message): ChatEntry => ({
        kind: "message",
        key: `message-${message.id}`,
        message,
      }),
    ),
    ...reports.map(
      (report): ChatEntry => ({
        kind: "report",
        key: `report-${report.id}`,
        report,
      }),
    ),
  ];
  const timestamp = (entry: ChatEntry) => {
    const value = Date.parse(
      entry.kind === "message"
        ? entry.message.created_at
        : entry.report.created_at,
    );
    return Number.isFinite(value) ? value : 0;
  };
  // Stable sorting preserves message order for equal timestamps, including
  // the user's message followed by the streaming assistant placeholder.
  return entries.sort((a, b) => timestamp(a) - timestamp(b));
}
