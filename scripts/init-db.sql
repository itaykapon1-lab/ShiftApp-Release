-- Auto-executed on first container init (empty data dir only).
-- Creates the test database alongside the default shiftapp_dev.
CREATE DATABASE shiftapp_test;
GRANT ALL PRIVILEGES ON DATABASE shiftapp_test TO shiftapp;

-- PG 15+ requires explicit GRANT on public schema for non-superusers.
\c shiftapp_test
GRANT ALL ON SCHEMA public TO shiftapp;
