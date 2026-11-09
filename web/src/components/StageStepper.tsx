import type { IndexingStage } from "../api/types";
import { STAGES, stageIndex } from "../lib/progress";

/** Compact six-step pipeline indicator for a file that is indexing: Read · Parse · Embed · Summarize · Link · Save. */
export function StageStepper({ stage }: { stage: IndexingStage | null }) {
  const current = stageIndex(stage);
  const label = current >= 0 ? `Step ${current + 1} of ${STAGES.length}: ${STAGES[current]!.long}` : "Starting";
  return (
    <ol className="stepper" aria-label={label}>
      {STAGES.map((s, i) => {
        const state = current < 0 || i > current ? "todo" : i === current ? "active" : "done";
        return (
          <li key={s.stage} className={`step is-${state}`} aria-current={state === "active" ? "step" : undefined} title={s.long}>
            <span className="step-bar" aria-hidden="true" />
            <span className="step-label">{s.short}</span>
          </li>
        );
      })}
    </ol>
  );
}
