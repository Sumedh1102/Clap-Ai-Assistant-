import { useCallback, useEffect, useReducer } from "react";
import type { Activity, ChatMessage, HudState } from "../types";

const MAX_MESSAGES = 60;
const MAX_ACTIVITIES = 30;

const initialState: HudState = {
  connected: false,
  state: "standby",
  detail: "",
  error: "",
  mic: "off",
  voice: null,
  mode: "",
  model: "",
  messages: [],
  activities: [],
  notice: "",
};

type Action =
  | { type: "event"; event: Record<string, unknown> }
  | { type: "connection"; connected: boolean }
  | { type: "local-message"; message: ChatMessage };

function upsert<T extends { id: number }>(items: T[], item: T, max: number): T[] {
  const index = items.findIndex((x) => x.id === item.id);
  const next = index === -1 ? [...items, item] : items.map((x, i) => (i === index ? item : x));
  return next.length > max ? next.slice(next.length - max) : next;
}

function reducer(hud: HudState, action: Action): HudState {
  if (action.type === "connection") return { ...hud, connected: action.connected };
  if (action.type === "local-message") return { ...hud, messages: upsert(hud.messages, action.message, MAX_MESSAGES) };

  const e = action.event;
  switch (e.type) {
    case "snapshot":
      return {
        ...hud,
        connected: true,
        state: e.state as HudState["state"],
        detail: (e.detail as string) ?? "",
        error: (e.error as string) ?? "",
        mic: e.mic as HudState["mic"],
        voice: e.voice as HudState["voice"],
        mode: (e.mode as string) ?? "",
        model: (e.model as string) ?? hud.model,
        messages: (e.messages as ChatMessage[]) ?? [],
        activities: (e.activities as Activity[]) ?? [],
      };
    case "state":
      return {
        ...hud,
        state: e.state as HudState["state"],
        detail: (e.detail as string) ?? "",
        error: e.state === "error" ? ((e.detail as string) ?? "") : "",
        notice: "",
      };
    case "message": {
      const { type: _t, ...message } = e;
      return { ...hud, messages: upsert(hud.messages, message as unknown as ChatMessage, MAX_MESSAGES) };
    }
    case "activity": {
      const { type: _t, ...activity } = e;
      return { ...hud, activities: upsert(hud.activities, activity as unknown as Activity, MAX_ACTIVITIES) };
    }
    case "mic":
      return { ...hud, mic: e.status as HudState["mic"] };
    case "voice": {
      const { type: _t, ts: _ts, ...voice } = e;
      return { ...hud, voice: voice as unknown as HudState["voice"] };
    }
    case "notice":
      return { ...hud, notice: (e.message as string) ?? "" };
    default:
      return hud;
  }
}

/**
 * Live CLAP state over server-sent events. On every (re)connect the server
 * sends a full snapshot, so the HUD always converges on the backend's truth.
 */
export function useClapEvents() {
  const [hud, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onopen = () => dispatch({ type: "connection", connected: true });
    source.onerror = () => dispatch({ type: "connection", connected: false });
    source.onmessage = (msg) => {
      try {
        dispatch({ type: "event", event: JSON.parse(msg.data) });
      } catch {
        /* ignore malformed frames */
      }
    };
    return () => source.close();
  }, []);

  const addLocalMessage = useCallback((message: ChatMessage) => {
    dispatch({ type: "local-message", message });
  }, []);

  return { hud, addLocalMessage };
}
