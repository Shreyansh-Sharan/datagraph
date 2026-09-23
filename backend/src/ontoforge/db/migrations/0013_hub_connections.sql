-- A domain may reference a connection held by the Polestar connection module (hub) rather
-- than the local table, so the references can no longer be foreign keys. Existence is checked
-- by the connections backend when a domain is updated, and deleting a connection detaches it.
ALTER TABLE domains
    DROP CONSTRAINT IF EXISTS domains_connection_id_fkey,
    DROP CONSTRAINT IF EXISTS domains_ai_connection_id_fkey;
