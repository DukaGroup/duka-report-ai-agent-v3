export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "member";
  active: number;
  created_at: string;
}
export interface Login {
  loginId: string;
  status: string;
  verificationUrl?: string;
  userCode?: string;
  error?: string;
}
export interface Subscription {
  connected: boolean;
  available: boolean;
  error?: string;
  account?: { email?: string; planType?: string };
  login?: Login;
}
export interface Model {
  id: string;
  model: string;
  displayName: string;
  isDefault: boolean;
}
export interface Conversation {
  id: string;
  title: string;
  model: string | null;
  updated_at: string;
  message_count?: number;
  preview?: string | null;
}
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: string;
}
export interface Report {
  id: string;
  title: string;
  template_id: string;
  conversation_id?: string | null;
  stage?: string | null;
  status: string;
  error: string | null;
  created_at: string;
  deleted_at?: string | null;
  document?: ReportDocument | null;
}
export interface ReportDocument {
  title: string;
  summary: string;
  sections: { heading: string; body: string }[];
  metrics: { label: string; value: string; explanation: string }[];
  limitations: string[];
}
export interface Template {
  id: string;
  name: string;
  description: string;
}
export interface Source {
  id: string;
  name: string;
  kind: string;
  status: string;
  description: string;
  last_error?: string | null;
  checked_at?: string | null;
  configuration_origin?: "saved" | "environment";
  error_scope?: "query" | "connection";
  connection_fields?: Record<string, boolean>;
}
export interface Dataset {
  id: string;
  source_id?: string;
  name: string;
  description: string;
  query_key?: string;
  enabled: number;
  status?: string;
  source?: string;
}
export interface Audit {
  id: string;
  action: string;
  actor_email: string;
  target_id: string | null;
  created_at: string;
}
export interface Overview {
  counts: Record<string, number>;
  active_runtimes: number;
  max_runtimes: number;
  voice: { available: boolean; model: string; loaded: boolean };
  database_sources: Source[];
  database_configuration: {
    environment: Record<string, boolean>;
    queries: { query_key: string; name?: string; error?: string }[];
  };
}
export interface VoiceStatus {
  available: boolean;
  model: string;
  loaded: boolean;
  note: string;
}
export interface RateWindow {
  usedPercent: number;
  windowDurationMins: number;
  resetsAt: number;
}
export interface RateLimits {
  primary?: RateWindow | null;
  secondary?: RateWindow | null;
}
