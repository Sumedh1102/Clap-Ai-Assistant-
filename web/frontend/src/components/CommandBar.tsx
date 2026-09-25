import { memo, useEffect, useRef, useState, type FormEvent } from "react";
import type { MicStatus } from "../types";

const MIC_SHORT: Record<MicStatus, string> = {
  off: "MIC OFF",
  armed: "MIC ARMED",
  capturing: "MIC LIVE",
  unavailable: "MIC UNAVAILABLE",
};

/** Bottom bar: microphone + link state, command input, current command. */
export const CommandBar = memo(function CommandBar({
  connected,
  mic,
  currentCommand,
  notice,
  onSubmit,
}: {
  connected: boolean;
  mic: MicStatus;
  currentCommand: string;
  notice: string;
  onSubmit: (text: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== inputRef.current) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const text = value.trim();
    if (!text || sending) return;
    setSending(true);
    setValue("");
    try {
      await onSubmit(text);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  return (
    <footer className="command-bar">
      <div className="command-bar__indicators">
        <span className={`indicator indicator--mic-${mic}`}>
          <i aria-hidden="true" />
          {MIC_SHORT[mic]}
        </span>
        <span className={`indicator ${connected ? "indicator--ok" : "indicator--bad"}`}>
          <i aria-hidden="true" />
          {connected ? "LINK ONLINE" : "LINK OFFLINE"}
        </span>
      </div>

      <form className="command-bar__form" onSubmit={submit}>
        <input
          ref={inputRef}
          className="command-bar__input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={sending ? "CLAP is working…" : "Type a command  ( / )"}
          disabled={sending || !connected}
          aria-label="Command"
          autoComplete="off"
          spellCheck={false}
        />
      </form>

      <div className="command-bar__current" title={currentCommand}>
        {notice ? (
          <span className="command-bar__notice">{notice}</span>
        ) : currentCommand ? (
          <>
            <span className="command-bar__label">COMMAND</span> {currentCommand}
          </>
        ) : (
          <span className="command-bar__label">NO COMMAND YET</span>
        )}
      </div>
    </footer>
  );
});
