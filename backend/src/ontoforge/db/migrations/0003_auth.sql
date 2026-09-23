-- Principals (who) with a role (what they may do), and hashed API keys for token auth.
CREATE TABLE principals (
    name       text PRIMARY KEY,
    role       text NOT NULL CHECK (role IN ('viewer', 'builder', 'reviewer', 'admin')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text NOT NULL,
    principal  text NOT NULL,
    role       text NOT NULL CHECK (role IN ('viewer', 'builder', 'reviewer', 'admin')),
    key_hash   text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);
