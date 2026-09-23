CREATE TABLE cohorts (
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    name              text NOT NULL,
    definition        jsonb NOT NULL,
    created_by        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (domain_version_id, name)
);
