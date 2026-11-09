import { useState } from "react";
import type { LinkVerdict } from "../api/types";

interface Props {
  value: LinkVerdict | null;
  /** Names the link for screen readers, e.g. "Pricing Strategy and Tier Design". */
  label: string;
  onVerdict: (v: LinkVerdict) => Promise<void>;
}

/** SL-3 confirm / hide buttons; PUT /api/links/{a}/{b}/feedback via onVerdict. */
export function FeedbackButtons({ value, label, onVerdict }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (v: LinkVerdict) => {
    setBusy(true);
    setError(null);
    try {
      await onVerdict(v);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const confirmed = value === "confirmed" || value === "added";
  return (
    <span className="feedback">
      <button
        type="button"
        className={`chip-btn ${confirmed ? "is-on" : ""}`}
        aria-pressed={confirmed}
        aria-label={`Confirm link between ${label}`}
        disabled={busy || confirmed}
        onClick={() => void send("confirmed")}
      >
        ✓ {confirmed ? "Confirmed" : "Useful"}
      </button>
      <button type="button" className="chip-btn" aria-label={`Hide link between ${label}`} disabled={busy} onClick={() => void send("hidden")}>
        Hide
      </button>
      {error && (
        <span role="alert" className="error small">
          {error}
        </span>
      )}
    </span>
  );
}
