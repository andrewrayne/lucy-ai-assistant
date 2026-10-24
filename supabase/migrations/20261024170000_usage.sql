-- Stage 13: what the assistant spends (Gemini tokens, Twilio calls), for /usage and the daily limit.

create table public.usage (
  id bigint generated always as identity primary key,
  day date not null,                       -- the owner's local date
  service text not null,                   -- 'gemini', 'gemini-live', 'twilio', ...
  model text not null default '',
  input_tokens bigint not null default 0,
  output_tokens bigint not null default 0,
  cost_usd numeric(12, 6) not null default 0,
  details jsonb,
  created_at timestamptz not null default now()
);

create index usage_day_idx on public.usage (day);

-- Only the server (service role) reads and writes it.
alter table public.usage enable row level security;
