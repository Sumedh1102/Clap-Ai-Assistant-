import { memo, useEffect, useMemo, useRef } from "react";
import type { Activity, ChatMessage } from "../types";

type Entry =
  | { kind: "message"; ts: number; key: string; message: ChatMessage }
  | { kind: "activity"; ts: number; key: string; activity: Activity };

const ROLE_LABEL: Record<ChatMessage["role"], string> = {
  user: "YOU",
  assistant: "CLAP",
  system: "SYSTEM",
};

const STATUS_LABEL: Record<Activity["status"], string> = {
  running: "EXECUTING",
  completed: "COMPLETED",
  failed: "FAILED",
};

/** Conversation timeline: messages and tool activity, interleaved by time. */
export const ConversationPanel = memo(function ConversationPanel({
  messages,
  activities,
}: {
  messages: ChatMessage[];
  activities: Activity[];
}) {
  const entries = useMemo<Entry[]>(() => {
    const all: Entry[] = [
      ...messages.map((m) => ({ kind: "message" as const, ts: m.ts, key: `m${m.id}`, message: m })),
      ...activities.map((a) => ({ kind: "activity" as const, ts: a.ts, key: `a${a.id}`, activity: a })),
    ];
    return all.sort((a, b) => a.ts - b.ts).slice(-40);
  }, [messages, activities]);

  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [entries]);

  return (
    <aside className="hud-panel hud-panel--left" aria-label="Conversation">
      <div className="hud-panel__title">CONVERSATION</div>
      <div className="conversation">
        {entries.length === 0 && <div className="conversation__empty">Say “CLAP”, or type a command below.</div>}
        {entries.map((entry) =>
          entry.kind === "message" ? (
            <div key={entry.key} className={`conv-entry conv-entry--${entry.message.role}`}>
              <div className="conv-entry__label">{ROLE_LABEL[entry.message.role]}</div>
              <div className="conv-entry__text">{entry.message.text}</div>
            </div>
          ) : (
            <div key={entry.key} className={`conv-entry conv-entry--activity conv-entry--${entry.activity.status}`}>
              <div className="conv-entry__label">
                ACTIVITY <span className="conv-entry__status">{STATUS_LABEL[entry.activity.status]}</span>
              </div>
              <div className="conv-entry__text">
                {entry.activity.label} · {entry.activity.action}
                {entry.activity.status === "failed" && entry.activity.error ? ` — ${entry.activity.error}` : ""}
              </div>
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>
    </aside>
  );
});
