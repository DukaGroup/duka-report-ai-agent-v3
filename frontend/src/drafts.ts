import type { Attachment } from "./types";
export type Draft = {
  draft: string;
  attachments: Attachment[];
  model: string;
  reasoningEffort: string;
  retryMessageId: string | null;
};
const key = (user: string) => `duka.drafts.${user}`;
export function loadDrafts(user: string): Map<string, Draft> {
  try {
    return new Map(JSON.parse(localStorage.getItem(key(user)) || "[]"));
  } catch {
    return new Map();
  }
}
export function saveDrafts(user: string, drafts: Map<string, Draft>) {
  try {
    localStorage.setItem(key(user), JSON.stringify([...drafts]));
  } catch {
    /* The in-memory draft remains available if browser storage is full. */
  }
}
