-- A domain reads from several sources: each is a connection (or the deployment's env source when
-- null) with its own catalog and ordered schemas. The first source is the primary one.
ALTER TABLE domains ADD COLUMN sources jsonb NOT NULL DEFAULT '[]'::jsonb;
UPDATE domains SET sources = jsonb_build_array(jsonb_build_object(
    'connection_id', connection_id::text, 'catalog', default_catalog, 'schemas', to_jsonb(schemas)))
WHERE connection_id IS NOT NULL OR default_catalog IS NOT NULL OR cardinality(schemas) > 0;
ALTER TABLE domains DROP COLUMN connection_id, DROP COLUMN default_catalog, DROP COLUMN schemas;
