-- A domain reads from several schemas of its source; the first one is the default the
-- catalog browser opens and short table names resolve against.
ALTER TABLE domains ADD COLUMN schemas text[] NOT NULL DEFAULT '{}';
UPDATE domains SET schemas = ARRAY[default_schema] WHERE default_schema IS NOT NULL AND default_schema <> '';
ALTER TABLE domains DROP COLUMN default_schema;
