-- Every activity, for the bell: builds, jobs, profiles, rule runs, design and lifecycle changes.
-- Denormalised (domain name, version number) on purpose: a row survives the version it was about.
CREATE TABLE notifications (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    kind        text NOT NULL,                     -- build.started | build.succeeded | job.running | dq.run | status.in_review | ...
    actor       text,
    via         text,                              -- assistant | mcp | null (the screens)
    domain_name text,
    version     int,
    table_name  text,
    title       text NOT NULL,
    body        text,
    link        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {screen, domain, version, table, tab}
    status      text NOT NULL DEFAULT 'info',      -- info | running | done | failed
    progress    text,                              -- what a running activity is doing right now
    ref_kind    text,                              -- build | job: the row a running activity keeps updating
    ref_id      text,
    audience    text NOT NULL DEFAULT 'all',       -- all | reviewers | actor
    detail      jsonb
);
CREATE UNIQUE INDEX notifications_ref ON notifications (ref_kind, ref_id) WHERE ref_id IS NOT NULL;
CREATE INDEX notifications_by_id ON notifications (id DESC);
CREATE INDEX notifications_running ON notifications (status) WHERE status = 'running';

CREATE TABLE notification_reads (
    principal       text NOT NULL,
    notification_id bigint NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
    read_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (principal, notification_id)
);
CREATE TABLE notification_watermarks (
    principal  text PRIMARY KEY,
    read_until bigint NOT NULL DEFAULT 0            -- "mark all read": everything up to this id
);
