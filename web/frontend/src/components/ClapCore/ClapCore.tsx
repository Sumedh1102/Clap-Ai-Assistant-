import { memo } from "react";
import { PredictiveArcCanvas } from "@designcodeio/threeui";
import "@designcodeio/threeui/style.css";
import "./ClapCore.css";

import type { AssistantState } from "../../types";

/**
 * CLAP's central visual: the registered ThreeUI PredictiveArcCanvas
 * (@designcodeio/threeui 1.2.0, variant "predictive"), rendered unmodified.
 *
 * Base configuration, exactly as specified for CLAP:
 *   mode="dark" speed={1.00} hue={0} saturation={1.00} brightness={1.00}
 *
 * The arc responds to real assistant state only through the component's own
 * public props. Its renderer reads them every frame, so changes apply without
 * re-creating the canvas. In STANDBY the values are exactly the base
 * configuration. The shader/renderer source is never touched.
 */
type ArcResponse = { speed: number; saturation: number; brightness: number };

const ARC_BASE: ArcResponse = { speed: 1.0, saturation: 1.0, brightness: 1.0 };

const ARC_RESPONSE: Record<AssistantState | "offline", ArcResponse> = {
  standby: ARC_BASE,
  listening: { speed: 1.35, saturation: 1.0, brightness: 1.08 },
  thinking: { speed: 1.8, saturation: 1.0, brightness: 1.05 },
  executing: { speed: 2.2, saturation: 1.0, brightness: 1.12 },
  speaking: { speed: 1.5, saturation: 1.0, brightness: 1.15 },
  error: { speed: 0.6, saturation: 0.35, brightness: 0.8 },
  offline: { speed: 0.5, saturation: 0.6, brightness: 0.7 },
};

export const STATE_NAMES: Record<AssistantState, string> = {
  standby: "STANDBY",
  listening: "LISTENING",
  thinking: "THINKING",
  executing: "EXECUTING",
  speaking: "SPEAKING",
  error: "ERROR",
};

export const STATE_MESSAGES: Record<AssistantState, string> = {
  standby: "CLAP ONLINE",
  listening: "LISTENING...",
  thinking: "PROCESSING...",
  executing: "EXECUTING ACTION...",
  speaking: "RESPONDING...",
  error: "SYSTEM ERROR",
};

const ArcStage = memo(function ArcStage({ speed, saturation, brightness }: ArcResponse) {
  return (
    <div className="shader-frame">
      <PredictiveArcCanvas
        mode="dark"
        speed={speed}
        hue={0}
        saturation={saturation}
        brightness={brightness}
      />
    </div>
  );
});

type ClapCoreProps = {
  state: AssistantState;
  detail: string;
  connected: boolean;
  /** Set false to keep the arc at its exact base configuration in every state. */
  reactive?: boolean;
};

export const ClapCore = memo(function ClapCore({ state, detail, connected, reactive = true }: ClapCoreProps) {
  const response = !reactive ? ARC_BASE : connected ? ARC_RESPONSE[state] : ARC_RESPONSE.offline;
  const visualState = connected ? state : "offline";

  return (
    <section className={`clap-core clap-core--${visualState}`} aria-label="CLAP assistant status">
      <ArcStage speed={response.speed} saturation={response.saturation} brightness={response.brightness} />

      <h1 className="clap-core__brand">CLAP</h1>

      <div className="clap-core__status" role="status" aria-live="polite">
        <div className="clap-core__chip">
          <span className="clap-core__dot" aria-hidden="true" />
          {connected ? STATE_NAMES[state] : "OFFLINE"}
        </div>
        <div className="clap-core__message">{connected ? STATE_MESSAGES[state] : "RECONNECTING..."}</div>
        <div className="clap-core__detail">{connected ? detail : "Waiting for the CLAP backend"}</div>
      </div>
    </section>
  );
});
