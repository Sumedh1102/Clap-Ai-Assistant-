import { memo } from "react";
import type { Activity, MicStatus, SystemMetrics, VoiceInfo } from "../types";

const MIC_LABEL: Record<MicStatus, string> = {
  off: "OFF",
  armed: "WAKE WORD ARMED",
  capturing: "CAPTURING",
  unavailable: "UNAVAILABLE",
};

function pct(value: number | null | undefined) {
  return value == null ? "—" : `${Math.round(value)}%`;
}

function uptime(seconds: number | undefined) {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

function voiceLabel(voice: VoiceInfo | null | undefined) {
  if (!voice) return "—";
  if (!voice.available) return "UNAVAILABLE";
  const provider = voice.provider === "elevenlabs" ? "ElevenLabs" : voice.provider === "macos" ? "macOS" : voice.provider;
  return `${provider}${voice.reference_voice ? " · CLAP voice" : " · approximation"}`;
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "warn" | "bad" | "good" }) {
  return (
    <div className="sys-row">
      <span className="sys-row__label">{label}</span>
      <span className={`sys-row__value${tone ? ` sys-row__value--${tone}` : ""}`}>{value}</span>
    </div>
  );
}

/** Real system information and the current/last tool activity. */
export const SystemPanel = memo(function SystemPanel({
  metrics,
  mic,
  voice,
  model,
  activity,
}: {
  metrics: SystemMetrics | null;
  mic: MicStatus;
  voice: VoiceInfo | null;
  model: string;
  activity: Activity | undefined;
}) {
  const voiceInfo = voice ?? metrics?.voice ?? null;
  return (
    <aside className="hud-panel hud-panel--right" aria-label="System">
      <div className="hud-panel__title">SYSTEM</div>
      <Row label="CPU" value={pct(metrics?.cpu_percent)} />
      <Row
        label="MEMORY"
        value={
          metrics?.memory_percent == null
            ? "—"
            : `${pct(metrics.memory_percent)} · ${metrics.memory_used_gb}/${metrics.memory_total_gb} GB`
        }
      />
      <Row label="CLAP PROCESS" value={metrics?.process_memory_mb == null ? "—" : `${metrics.process_memory_mb} MB`} />
      <Row label="MICROPHONE" value={MIC_LABEL[mic]} tone={mic === "unavailable" ? "bad" : mic === "capturing" ? "good" : undefined} />
      <Row label="VOICE" value={voiceLabel(voiceInfo)} tone={voiceInfo && !voiceInfo.available ? "warn" : undefined} />
      <Row label="MODEL" value={model || metrics?.model || "—"} />
      <Row label="UPTIME" value={uptime(metrics?.uptime_s)} />
      {voiceInfo && !voiceInfo.available && voiceInfo.reason && <div className="sys-note">{voiceInfo.reason}</div>}

      <div className="hud-panel__title hud-panel__title--spaced">ACTIVE TASK</div>
      {activity ? (
        <div className={`task task--${activity.status}`}>
          <div className="task__status">{activity.status === "running" ? "EXECUTING" : activity.status.toUpperCase()}</div>
          <Row label="TOOL" value={activity.label} />
          <Row label="ACTION" value={activity.action} />
          {activity.status === "failed" && activity.error && <div className="sys-note sys-note--bad">{activity.error}</div>}
        </div>
      ) : (
        <div className="sys-note">No tool activity yet.</div>
      )}
    </aside>
  );
});
