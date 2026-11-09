import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { LinkEvidenceView, LinkVerdict, Passage } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { docKey } from "../lib/graphModel";
import { FeedbackButtons } from "./FeedbackButtons";
import { Modal } from "./Modal";

interface Props {
  a: string;
  b: string;
  onClose: () => void;
  onFeedback: (a: string, b: string, verdict: LinkVerdict) => Promise<void>;
  onOpen: (key: string, label: string) => void;
}

function PassageCard({ title, passage, onOpen }: { title: string; passage: Passage | null; onOpen: () => void }) {
  return (
    <figure className="passage">
      <figcaption>
        <button type="button" className="link-btn strong" onClick={onOpen}>
          {title}
        </button>
        {passage && passage.heading_path.length > 0 && <div className="muted small">{passage.heading_path.join(" › ")}</div>}
      </figcaption>
      {passage ? <blockquote>{passage.text}</blockquote> : <p className="muted">No matching passage stored for this side.</p>}
    </figure>
  );
}

/** SL-2 "Why connected?": score, one-line reason and the matching passages side by side. */
export function EvidenceDialog({ a, b, onClose, onFeedback, onOpen }: Props) {
  const { data, error, loading } = useAsync((signal) => api.linkEvidence(a, b, undefined, signal), [a, b]);
  const [feedback, setFeedback] = useState<LinkVerdict | null>(null);
  useEffect(() => setFeedback(data?.feedback ?? null), [data]);

  const open = (view: LinkEvidenceView, side: "a" | "b") => {
    const end = view[side];
    onOpen(docKey(end.document_id), end.title);
    onClose();
  };

  return (
    <Modal title="Why connected?" onClose={onClose} className="evidence">
      {loading && !data && <p aria-busy="true">Loading evidence…</p>}
      {error && <p role="alert">{error instanceof ApiError && error.status === 404 ? "These documents are no longer linked." : `Could not load evidence: ${error.message}`}</p>}
      {data && (
        <div className="evidence-body">
          <div className="evidence-summary">
            {data.origin === "manual" ? (
              <span className="badge">Added by you</span>
            ) : (
              <span className="score" aria-label={`Similarity ${Math.round((data.score ?? 0) * 100)} percent`}>
                {Math.round((data.score ?? 0) * 100)}% similar
              </span>
            )}
            <p className="reason">{data.reason ?? <span className="muted">Reason pending: Claude has not explained this link yet.</span>}</p>
          </div>
          <div className="passages">
            <PassageCard title={data.a.title} passage={data.a_passage} onOpen={() => open(data, "a")} />
            <PassageCard title={data.b.title} passage={data.b_passage} onOpen={() => open(data, "b")} />
          </div>
          <div className="evidence-actions">
            <span className="muted small">Is this link useful?</span>
            <FeedbackButtons
              value={feedback}
              label={`${data.a.title} and ${data.b.title}`}
              onVerdict={async (v) => {
                await onFeedback(data.pair.a, data.pair.b, v);
                setFeedback(v);
                if (v === "hidden") onClose();
              }}
            />
          </div>
        </div>
      )}
    </Modal>
  );
}
