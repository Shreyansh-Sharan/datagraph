-- Incremental builds: every triple remembers the source table it came from, and a version keeps
-- the signature of each mapped table as of its last successful build.
ALTER TABLE triples ADD COLUMN source_table text;
CREATE INDEX triples_by_source ON triples (domain_version_id, source_table);

CREATE TABLE build_state (
    domain_version_id uuid PRIMARY KEY REFERENCES domain_versions(id) ON DELETE CASCADE,
    mapping_hash      text NOT NULL,
    tables            jsonb NOT NULL DEFAULT '{}'::jsonb,   -- table name -> signature at the last successful load
    updated_at        timestamptz NOT NULL DEFAULT now()
);
