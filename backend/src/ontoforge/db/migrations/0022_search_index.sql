-- Entity search runs ILIKE '%text%' over a version's literals and subjects. Trigram indexes let
-- Postgres answer that from the index instead of scanning millions of rows (3.4 s -> tens of ms).
-- The extension goes to public so every schema's search path finds its operator classes.
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
CREATE INDEX IF NOT EXISTS triples_object_trgm ON triples USING gin (object public.gin_trgm_ops) WHERE object_type = 'literal';
CREATE INDEX IF NOT EXISTS triples_subject_trgm ON triples USING gin (subject public.gin_trgm_ops);
