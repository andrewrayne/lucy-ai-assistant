-- Stage 5: morning brief, reminders and the owner's current location.

-- Small key/value store for owner settings that change at runtime
-- (current city and time zone). Server-only, like every other table.
create table public.owner_settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.owner_settings enable row level security;
revoke all on public.owner_settings from anon, authenticated;
grant select, insert, update, delete on public.owner_settings to service_role;

-- The morning brief is a recurring row in reminders with kind = 'brief'.
-- recurrence holds a cron expression evaluated in the owner's time zone,
-- e.g. '0 8 * * *' for every day at 08:00.
alter table public.reminders
  add column kind text not null default 'reminder' check (kind in ('reminder', 'brief'));

-- At most one active morning brief.
create unique index reminders_one_active_brief on public.reminders (kind)
  where kind = 'brief' and status = 'pending';
