import { useCallback, useMemo } from "react";
import { ClapCore } from "./components/ClapCore/ClapCore";
import { CommandBar } from "./components/CommandBar";
import { ConversationPanel } from "./components/ConversationPanel";
import { SystemPanel } from "./components/SystemPanel";
import { useClapEvents } from "./hooks/useClapEvents";
import { useSystemMetrics } from "./hooks/useSystemMetrics";

export default function App() {
  const { hud, addLocalMessage } = useClapEvents();
  const metrics = useSystemMetrics();

  const currentCommand = useMemo(() => {
    for (let i = hud.messages.length - 1; i >= 0; i--) {
      if (hud.messages[i].role === "user") return hud.messages[i].text;
    }
    return "";
  }, [hud.messages]);

  const activity = hud.activities.length ? hud.activities[hud.activities.length - 1] : undefined;

  const sendCommand = useCallback(
    async (text: string) => {
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text }),
        });
        const data = await res.json().catch(() => ({}));
        // The event stream normally delivers the reply; this covers a dropped stream.
        if (data.ok && data.reply && data.message_id != null) {
          addLocalMessage({ id: data.message_id, role: "assistant", text: data.reply, source: "web", ts: Date.now() / 1000 });
        } else if (data.error) {
          // Same id as the server-side event when there is one, so it is never shown twice.
          const id = data.message_id ?? -Date.now();
          addLocalMessage({ id, role: "system", text: data.error, source: "web", ts: Date.now() / 1000 });
        }
      } catch {
        addLocalMessage({ id: -Date.now(), role: "system", text: "CLAP cannot reach its server.", source: "web", ts: Date.now() / 1000 });
      }
    },
    [addLocalMessage],
  );

  return (
    <div className="hud">
      <ClapCore state={hud.state} detail={hud.detail} connected={hud.connected} />
      <div className="hud-vignette" aria-hidden="true" />
      <ConversationPanel messages={hud.messages} activities={hud.activities} />
      <SystemPanel metrics={metrics} mic={hud.mic} voice={hud.voice} model={hud.model} activity={activity} />
      <CommandBar
        connected={hud.connected}
        mic={hud.mic}
        currentCommand={currentCommand}
        notice={hud.notice}
        onSubmit={sendCommand}
      />
      <a className="hud-console-link" href="/console">
        CONSOLE
      </a>
    </div>
  );
}
