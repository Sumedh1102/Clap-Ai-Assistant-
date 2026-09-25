export type AssistantState = "standby" | "listening" | "thinking" | "executing" | "speaking" | "error";

export type MicStatus = "off" | "armed" | "capturing" | "unavailable";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "system";
  text: string;
  source: string;
  ts: number;
}

export interface Activity {
  id: number;
  tool: string;
  label: string;
  action: string;
  status: "running" | "completed" | "failed";
  error: string;
  ts: number;
  ended: number | null;
}

export interface VoiceInfo {
  available: boolean;
  provider: string | null;
  voice: string | null;
  reference_voice?: boolean;
  reason: string;
  last_error?: string;
}

export interface HudState {
  connected: boolean;
  state: AssistantState;
  detail: string;
  error: string;
  mic: MicStatus;
  voice: VoiceInfo | null;
  mode: string;
  model: string;
  messages: ChatMessage[];
  activities: Activity[];
  notice: string;
}

export interface SystemMetrics {
  platform: string;
  uptime_s: number;
  metrics_available: boolean;
  cpu_percent: number | null;
  memory_percent: number | null;
  memory_used_gb: number | null;
  memory_total_gb: number | null;
  process_memory_mb: number | null;
  model: string;
  mic: MicStatus;
  voice: VoiceInfo;
  state: AssistantState;
  busy: boolean;
}
