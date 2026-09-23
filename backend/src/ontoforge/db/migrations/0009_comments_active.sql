CREATE TABLE comments (
    id                bigserial PRIMARY KEY,
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    author            text NOT NULL,
    body              text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX comments_by_version ON comments (domain_version_id, id);

ALTER TABLE domains ADD COLUMN active_version_id uuid REFERENCES domain_versions(id) ON DELETE SET NULL;
