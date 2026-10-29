import type { Message, Report } from "./types";

type ChatEntry =
  | { kind: "message"; key: string; message: Message }
  | { kind: "report"; key: string; report: Report };

/** Keep report cards at their creation point rather than after every new message. */
export function buildChatTimeline(
  messages: Message[],
  reports: Report[],
  // A reply keeps the key it had while streaming after it gets its saved id,
  // so it is not rebuilt (and re-animated) the moment it finishes.
  keyFor: (id: string) => string | undefined = () => undefined,
): ChatEntry[] {
  const messageEntries: ChatEntry[] = messages.map(
    (message): ChatEntry => ({
      kind: "message",
      key: `message-${keyFor(message.id) ?? message.id}`,
      message,
    }),
  );
  const reportEntries: ChatEntry[] = reports.map(
    (report): ChatEntry => ({
      kind: "report",
      key: `report-${report.id}`,
      report,
    }),
  );
  const timestamp = (entry: ChatEntry) => {
    const value = Date.parse(
      entry.kind === "message"
        ? entry.message.created_at
        : entry.report.created_at,
    );
    return Number.isFinite(value) ? value : undefined;
  };
  // Message order is authoritative. Temporary replies use the browser clock;
  // sorting them against server timestamps can move a live reply to the top.
  // Only sort report cards, then merge them without reordering any messages.
  reportEntries.sort(
    (a, b) => (timestamp(a) ?? Infinity) - (timestamp(b) ?? Infinity),
  );
  const entries: ChatEntry[] = [];
  let reportIndex = 0;
  let previousTime = 0;
  for (const entry of messageEntries) {
    const time = Math.max(previousTime, timestamp(entry) ?? previousTime);
    while (
      reportIndex < reportEntries.length &&
      (timestamp(reportEntries[reportIndex]) ?? Infinity) < time
    ) {
      entries.push(reportEntries[reportIndex++]);
    }
    entries.push(entry);
    previousTime = time;
  }
  return entries.concat(reportEntries.slice(reportIndex));
}
