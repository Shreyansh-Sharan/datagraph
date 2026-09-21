-- Named connections (source warehouses and AI providers) and per-domain settings behind the
-- Home cards and the Configure screen. Secrets are stored encrypted (see ontoforge.connectors.secrets).
CREATE TABLE connections (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL UNIQUE,
    kind        text NOT NULL CHECK (kind IN ('postgres', 'databricks', 'sqlserver', 'azure_openai')),
    config      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- non-secret settings (host, catalog, deployment, ...)
    secret      text,                                  -- encrypted token / password / API key, never returned by the API
    last_test   jsonb,                                 -- {ok, title, detail, latency_ms, at}
    created_by  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE domains
    ADD COLUMN connection_id    uuid REFERENCES connections(id) ON DELETE SET NULL,
    ADD COLUMN ai_connection_id uuid REFERENCES connections(id) ON DELETE SET NULL,
    ADD COLUMN default_catalog  text,
    ADD COLUMN default_schema   text,
    ADD COLUMN materialization  text NOT NULL DEFAULT 'none' CHECK (materialization IN ('none', 'view', 'table')),
    ADD COLUMN target_schema    text;
