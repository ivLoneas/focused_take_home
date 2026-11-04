CREATE TABLE IF NOT EXISTS web_sessions (
    session_hash text PRIMARY KEY CHECK (length(session_hash) = 64),
    state jsonb NOT NULL,
    version bigint NOT NULL DEFAULT 0,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS web_sessions_expiry ON web_sessions (expires_at);
