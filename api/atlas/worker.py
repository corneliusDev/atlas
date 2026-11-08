"""Worker loop + VaultScanner (`python -m atlas.worker`). Stub: track C implements.

Loop contract (PRD Output 1 / 4):
  claim(lease=5 min) -> pipeline.run(job) -> complete(outcome) | fail(error) -> RetryDecision.
  Backoff: 2**attempt * 10 s; max 3 attempts then FAILED (non-retryable errors fail at once).
  When the queue drains: enqueue Recluster(vault) (at most one pending per vault).
  On startup: settings.require_llm_key(), apply migrations, scan the default vault.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("worker loop: implemented by track C")


if __name__ == "__main__":
    main()
