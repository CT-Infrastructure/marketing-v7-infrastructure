\set ON_ERROR_STOP on
-- Bootstrap administrator only, one fresh disposable/site-approved cluster.
-- Caller provides SCRAM verifiers via psql variables, never command line values.
CREATE ROLE app_a_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE app_a_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'a_migrator_verifier';
CREATE ROLE app_a_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'a_runtime_verifier';
CREATE ROLE app_b_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE app_b_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'b_migrator_verifier';
CREATE ROLE app_b_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'b_runtime_verifier';
GRANT app_a_owner TO app_a_migrator;
GRANT app_b_owner TO app_b_migrator;
CREATE DATABASE app_a OWNER app_a_owner;
CREATE DATABASE app_b OWNER app_b_owner;
REVOKE ALL ON DATABASE app_a, app_b FROM PUBLIC;
GRANT CONNECT ON DATABASE app_a TO app_a_migrator, app_a_runtime;
GRANT CONNECT ON DATABASE app_b TO app_b_migrator, app_b_runtime;
ALTER ROLE app_a_runtime IN DATABASE app_a SET search_path = pg_catalog, ledger;
ALTER ROLE app_b_runtime IN DATABASE app_b SET search_path = pg_catalog, ledger;
ALTER ROLE app_a_runtime SET statement_timeout = '15s';
ALTER ROLE app_b_runtime SET statement_timeout = '15s';
