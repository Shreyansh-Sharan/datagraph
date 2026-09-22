-- The assistant's threads: one conversation per question thread, its messages with the tool calls made.
CREATE TABLE conversations (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor      text NOT NULL,
    domain     text,
    title      text NOT NULL,
    context    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_by_actor ON conversations (actor, updated_at DESC);

CREATE TABLE messages (
    id              bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            text NOT NULL,       -- user | assistant | tool
    content         text,
    tool_calls      jsonb,               -- [{id, name, arguments}] on an assistant message that called tools
    tool_call_id    text,                -- on a tool message: which call it answers
    name            text,                -- on a tool message: the tool
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_by_conversation ON messages (conversation_id, id);
