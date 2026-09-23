-- Persistent background jobs: survive a restart, so a poller and the startup sweep both read
-- the same table instead of an in-memory dict that a dead process takes its state down with.
CREATE TABLE jobs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind             text NOT NULL,
    version_id       uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    actor            text,
    label            text,
    status           text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    progress         text,
    cancel_requested boolean NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now(),   -- queued order, for "latest" when several share a started_at
    started_at       timestamptz,
    heartbeat_at     timestamptz,                          -- touched every ~5 s while running: a stale one means a dead worker
    finished_at      timestamptz,
    error            text,
    result           jsonb
);
CREATE INDEX jobs_by_version ON jobs (version_id, created_at DESC);
CREATE INDEX jobs_running ON jobs (status) WHERE status IN ('queued', 'running');
