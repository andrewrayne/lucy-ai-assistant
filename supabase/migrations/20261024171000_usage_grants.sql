-- The project revokes default table privileges (see lock_rls_auto_enable), so the server's role needs an
-- explicit grant on new tables.
grant select, insert on public.usage to service_role;
grant usage, select on sequence public.usage_id_seq to service_role;
