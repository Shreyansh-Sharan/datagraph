-- Per-version snapshot of source table metadata (what the mapping was designed against).
CREATE TABLE metadata_snapshots (
    domain_version_id uuid NOT NULL REFERENCES domain_versions(id) ON DELETE CASCADE,
    table_name        text NOT NULL,
    comment           text,
    columns           jsonb NOT NULL,   -- [{name, type, comment}]
    primary_key       jsonb NOT NULL,   -- [col, ...]
    foreign_keys      jsonb NOT NULL,   -- [{columns, references, referenced_columns}]
    captured_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (domain_version_id, table_name)
);
