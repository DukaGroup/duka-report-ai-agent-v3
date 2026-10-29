export interface User {
  id: string;
  email: string;
  name: string;
  role: "devs" | "president" | "manager";
  active: number;
  created_at: string;
  intro_pending?: boolean;
}
export type Provider = "chatgpt" | "claude";
export interface Login {
  loginId: string;
  status: string;
  verificationUrl?: string;
  userCode?: string;
  error?: string;
  provider?: Provider;
  requiresCode?: boolean;
}
export interface Subscription {
  can_respond?: boolean;
  connected: boolean;
  available: boolean;
  error?: string;
  account?: { email?: string; planType?: string };
  login?: Login;
  provider_id?: Provider;
}
export interface Model {
  supported_reasoning_efforts?: string[];
  default_reasoning_effort?: string | null;
  id: string;
  model: string;
  displayName: string;
  isDefault: boolean;
}
export interface Conversation {
  deleted_at?: string | null;
  notification_pending?: boolean;
  reasoning_effort?: string | null;
  id: string;
  title: string;
  model: string | null;
  updated_at: string;
  running?: boolean;
  message_count?: number;
  preview?: string | null;
}
export interface ProgressStep {
  id: string;
  label: string;
  kind: string;
}
export interface Message {
  steps?: ProgressStep[];
  notification_ready?: boolean;
  notification_pending?: boolean;
  report_count?: number;
  id: string;
  completed_at?: string | null;
  created_at: string;
  role: "user" | "assistant";
  content: string;
  status: string;
  attachments?: Attachment[];
}
export interface Attachment {
  id: string;
  name: string;
  size: number;
  kind: string;
  purpose: "analysis" | "template";
  tables: { id: string; name: string; row_count: number }[];
  format: Record<string, unknown>;
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
  enabled?: number;
  database_scope?: "all" | "default";
  credential_storage?: string;
  env_prefix?: string;
  tls?: {
    encryption?: "require" | "request" | "off";
    warnings?: string[];
    encrypt: boolean;
    validate_certificate: boolean;
    custom_ca: boolean;
    server_name_configured: boolean;
  };
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
