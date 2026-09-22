-- A mapping change no longer forces a full build: the plan compares, per source table, the hash of
-- the selects that produced its triples at the last successful load with the ones compiled now.
ALTER TABLE build_state ADD COLUMN selects jsonb NOT NULL DEFAULT '{}'::jsonb;   -- table name -> hash of its selects' SQL
