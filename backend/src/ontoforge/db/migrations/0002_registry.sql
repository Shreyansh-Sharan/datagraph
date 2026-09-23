-- Control plane: domains, versions with lifecycle, reviews, build runs, audit trail.
-- Data plane: one shared triple table keyed by domain version.

CREATE TABLE domains (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name          text NOT NULL UNIQUE,
    description   text,
    base_iri      text NOT NULL,
    review_quorum int  NOT NULL DEFAULT 1 CHECK (review_quorum >= 0),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE domain_versions (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id        uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    version          int  NOT NULL,
    status           text NOT NULL CHECK (status IN ('draft', 'in_review', 'published', 'archived')),
    ontology_ttl     text,
    mapping          jsonb,
    r2rml_ttl        text,
    editor           text,
    lease_expires_at timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domain_id, version)
);
-- At most one draft per domain.
CREATE UNIQUE INDEX domain_versions_one_draft ON domain_versions (domain_id) WHERE status = 'draft';

CREATE TABLE reviews (
    id                bigserial PRIMARY KEY,
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    reviewer          text NOT NULL,
    approved          boolean NOT NULL,
    comment           text,
    review_round      int NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE build_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    status            text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    actor             text,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    triple_count      bigint,
    error             text,
    steps             jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX build_runs_by_version ON build_runs (domain_version_id, started_at DESC);

CREATE TABLE audit_log (
    id                bigserial PRIMARY KEY,
    domain_version_id uuid REFERENCES domain_versions(id) ON DELETE CASCADE,
    actor             text,
    action            text NOT NULL,
    detail            jsonb,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_by_version ON audit_log (domain_version_id, id);

CREATE TABLE triples (
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    subject           text NOT NULL,
    predicate         text NOT NULL,
    object            text NOT NULL,
    object_type       text NOT NULL CHECK (object_type IN ('iri', 'literal', 'bnode')),
    datatype          text,
    lang              text,
    inferred          boolean NOT NULL DEFAULT false,
    object_key        text GENERATED ALWAYS AS (md5(object)) STORED
);
CREATE INDEX triples_sp  ON triples (domain_version_id, subject, predicate);
CREATE INDEX triples_po  ON triples (domain_version_id, predicate, object_key);
CREATE INDEX triples_o   ON triples (domain_version_id, object_key);
