-- Profiles, data-quality rules with their runs, and the glossary (terms and KPI metrics) of a domain.
CREATE TABLE table_profiles (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    table_name        text NOT NULL,
    profiled_at       timestamptz NOT NULL DEFAULT now(),
    actor             text,
    sample_pct        numeric NOT NULL DEFAULT 100,
    row_count         bigint,
    size_bytes        bigint,
    last_modified     timestamptz,
    duplicate_keys    bigint,
    columns           jsonb NOT NULL,   -- [{name, type, nulls, null_rate, distinct, min, max, top, top_share}]
    UNIQUE (domain_version_id, table_name)
);

CREATE TABLE dq_rules (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    table_name        text NOT NULL,
    name              text NOT NULL,
    column_name       text,
    kind              text NOT NULL,     -- not_null | unique | in_set | range | regex | referential | freshness | row_count | custom
    dimension         text NOT NULL,     -- completeness | uniqueness | validity | consistency | timeliness | volume
    params            jsonb NOT NULL DEFAULT '{}'::jsonb,
    threshold         numeric NOT NULL DEFAULT 0.95,
    owner             text,
    origin            text NOT NULL DEFAULT 'manual',   -- manual | ai
    enabled           boolean NOT NULL DEFAULT true,
    created_by        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dq_rules_by_table ON dq_rules (domain_version_id, table_name, created_at);

CREATE TABLE dq_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    table_name        text NOT NULL,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    actor             text,
    score             numeric,
    status            text NOT NULL DEFAULT 'running',   -- running | succeeded | failed
    error             text
);
CREATE INDEX dq_runs_by_table ON dq_runs (domain_version_id, table_name, started_at DESC);

CREATE TABLE dq_results (
    id         bigserial PRIMARY KEY,
    run_id     uuid NOT NULL REFERENCES dq_runs(id) ON DELETE CASCADE,
    rule_id    uuid NOT NULL REFERENCES dq_rules(id) ON DELETE CASCADE,
    pass_rate  numeric,
    passed     bigint,
    failed     bigint,
    total      bigint,
    status     text NOT NULL,   -- passing | warning | failing | error
    error      text,
    ran_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dq_results_by_rule ON dq_results (rule_id, ran_at DESC);

CREATE TABLE glossary_terms (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id   uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    kind        text NOT NULL,                 -- term | metric
    name        text NOT NULL,
    definition  text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'draft', -- draft | pending | approved | certified
    schema_name text,
    table_name  text,
    columns     jsonb NOT NULL DEFAULT '[]'::jsonb,
    class_name  text,
    formula     text,
    unit        text,
    frequency   text,
    owner       text,
    created_by  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domain_id, kind, name)
);
CREATE INDEX glossary_by_domain ON glossary_terms (domain_id, created_at);
