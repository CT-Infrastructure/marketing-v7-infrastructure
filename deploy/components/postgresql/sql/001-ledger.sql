\set ON_ERROR_STOP on
-- Connect as the selected app migrator; variables owner/runtime are identifiers.
BEGIN;
SET LOCAL ROLE :"owner";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA ledger AUTHORIZATION :"owner";
REVOKE ALL ON SCHEMA ledger FROM PUBLIC;
GRANT USAGE ON SCHEMA ledger TO :"runtime";
CREATE TABLE ledger.actions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 adapter text NOT NULL, account_ref text NOT NULL,
 action_key text NOT NULL CHECK (action_key ~ '^sha256:[0-9a-f]{64}$'),
 client_id text NOT NULL, source_system text NOT NULL, source_event_id text NOT NULL,
 action_scope text NOT NULL, approved_revision text NOT NULL,
 payload_ref text NOT NULL, approval_ref text,
 outbound_state text NOT NULL DEFAULT 'HOLD' CHECK (outbound_state = 'HOLD'),
 UNIQUE(adapter, account_ref, action_key),
 UNIQUE(adapter, account_ref, client_id, source_system, source_event_id, action_scope, approved_revision)
);
-- Append-only operational intents; no native application tables or dispatch logic.
GRANT SELECT, INSERT ON ledger.actions TO :"runtime";
GRANT USAGE ON SEQUENCE ledger.actions_id_seq TO :"runtime";
COMMIT;
