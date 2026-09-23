ALTER TABLE domains ADD COLUMN mcp_policy jsonb NOT NULL DEFAULT '{"exposed": true}'::jsonb;
