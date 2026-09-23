-- Table-level profile facts: exact duplicate rows, share of empty cells, the detected row key.
ALTER TABLE table_profiles ADD COLUMN duplicate_rows bigint;
ALTER TABLE table_profiles ADD COLUMN missing_cells numeric;
ALTER TABLE table_profiles ADD COLUMN row_key jsonb NOT NULL DEFAULT '[]'::jsonb;
