-- Live per-file indexing progress (UP-4 tray). Written only by the JobQueue:
--   claim         -> started_at = now(), stage = 'reading'
--   report_stage  -> stage = <stage>   (own autocommit statement, best-effort, running rows only)
--   complete/fail -> stage = NULL      (started_at kept, so done rows give the duration)
ALTER TABLE jobs
    ADD COLUMN stage text NULL
        CHECK (stage IN ('reading', 'parsing', 'embedding', 'enriching', 'linking', 'saving')),
    ADD COLUMN started_at timestamptz NULL;

-- avg_seconds_per_file: most recent done upserts per vault.
CREATE INDEX jobs_done_upsert_idx ON jobs (vault_id, finished_at DESC)
    WHERE state = 'done' AND kind = 'upsert';
