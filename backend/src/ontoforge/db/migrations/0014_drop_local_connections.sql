-- Connections live in the Polestar connection module (a separate service); datagraph keeps
-- only the hub connection ids on domains. The short-lived local table goes away.
DROP TABLE IF EXISTS connections;
