CREATE TABLE analytics_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    scope             text NOT NULL,            -- centralities | communities
    status            text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    actor             text,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    nodes             int,
    edges             int,
    components        int,
    avg_degree        double precision,
    density           double precision,
    duration_seconds  double precision,
    error             text,
    results           jsonb
);
CREATE INDEX analytics_runs_by_version ON analytics_runs (domain_version_id, started_at DESC);
