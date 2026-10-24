-- Stage 9: overview of the owner's AI agents.

-- When the owner was alerted about this run (failed, or stuck in 'running').
-- Each problem is alerted once.
alter table public.agent_runs add column updated_at timestamptz not null default now();
alter table public.agent_runs add column alerted_at timestamptz;

-- Fast lookups for the alert loop.
create index agent_runs_needs_alert_idx on public.agent_runs (created_at)
  where alerted_at is null and status in ('failed', 'running');
