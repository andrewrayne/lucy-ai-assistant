-- Stage 3: memory.
-- Every table is private: RLS is on with no policies, the Data API roles
-- (anon, authenticated) get no grants, and only the server's service key
-- (service_role) can read and write.

create extension if not exists vector with schema extensions;

-- Every message from every channel, with an embedding for semantic search.
create table public.messages (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  channel text not null default 'telegram'
    check (channel in ('telegram', 'voice', 'call', 'jarvis', 'phone')),
  chat_id bigint,
  -- 'event' rows mark things like "/new conversation"; they are not dialogue.
  role text not null check (role in ('user', 'assistant', 'event')),
  content text not null,
  embedding extensions.vector(768),
  summarized_at timestamptz
);
create index messages_created_at_idx on public.messages (created_at desc);
create index messages_unsummarized_idx on public.messages (created_at) where summarized_at is null;
create index messages_embedding_idx on public.messages
  using hnsw (embedding extensions.vector_cosine_ops);

-- Long-term facts about the owner, plus one summary per past day.
create table public.memories (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  kind text not null default 'fact'
    check (kind in ('fact', 'preference', 'person', 'project', 'summary')),
  content text not null,
  period_start date, -- for summaries: the day they cover
  embedding extensions.vector(768),
  constraint summary_has_day check (kind <> 'summary' or period_start is not null)
);
create unique index memories_one_summary_per_day on public.memories (period_start) where kind = 'summary';
create index memories_embedding_idx on public.memories
  using hnsw (embedding extensions.vector_cosine_ops);

-- Corrections from the owner, injected into the system prompt (stage 7).
create table public.lessons (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  content text not null,
  active boolean not null default true
);
create index lessons_active_idx on public.lessons (created_at) where active;

-- Task instructions the assistant can load or write itself (stage 7).
create table public.skills (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  name text not null unique,
  description text not null,
  instructions text not null
);

-- Reminders and scheduled items, checked every minute (stage 5).
create table public.reminders (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  chat_id bigint not null,
  text text not null,
  due_at timestamptz not null,
  recurrence text, -- e.g. a cron expression; null for one-off reminders
  status text not null default 'pending' check (status in ('pending', 'sent', 'cancelled')),
  sent_at timestamptz
);
create index reminders_due_idx on public.reminders (due_at) where status = 'pending';

-- Status reports from the owner's other agents (stage 9).
create table public.agent_runs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  agent text not null,
  status text not null check (status in ('running', 'success', 'failed')),
  summary text,
  details jsonb not null default '{}'::jsonb
);
create index agent_runs_agent_created_idx on public.agent_runs (agent, created_at desc);

-- Semantic search over messages, optionally limited to a time window.
create function public.match_messages(
  query_embedding extensions.vector(768),
  match_count int default 8,
  since timestamptz default null,
  until timestamptz default null
)
returns table (id bigint, created_at timestamptz, channel text, role text, content text, similarity float)
language sql stable
security invoker
set search_path = ''
set hnsw.iterative_scan = relaxed_order -- keep finding rows when the time filter is strict
as $$
  select m.id, m.created_at, m.channel, m.role, m.content,
         1 - (m.embedding operator(extensions.<=>) query_embedding) as similarity
  from public.messages m
  where m.embedding is not null
    and m.role <> 'event'
    and (since is null or m.created_at >= since)
    and (until is null or m.created_at < until)
  order by m.embedding operator(extensions.<=>) query_embedding
  limit match_count;
$$;

-- Semantic search over long-term memories and daily summaries.
create function public.match_memories(
  query_embedding extensions.vector(768),
  match_count int default 5,
  kinds text[] default null
)
returns table (id bigint, created_at timestamptz, kind text, content text, period_start date, similarity float)
language sql stable
security invoker
set search_path = ''
set hnsw.iterative_scan = relaxed_order
as $$
  select m.id, m.created_at, m.kind, m.content, m.period_start,
         1 - (m.embedding operator(extensions.<=>) query_embedding) as similarity
  from public.memories m
  where m.embedding is not null
    and (kinds is null or m.kind = any (kinds))
  order by m.embedding operator(extensions.<=>) query_embedding
  limit match_count;
$$;

-- Lock everything down to the server.
alter table public.messages enable row level security;
alter table public.memories enable row level security;
alter table public.lessons enable row level security;
alter table public.skills enable row level security;
alter table public.reminders enable row level security;
alter table public.agent_runs enable row level security;

revoke all on public.messages, public.memories, public.lessons, public.skills,
  public.reminders, public.agent_runs from anon, authenticated;
grant select, insert, update, delete on public.messages, public.memories, public.lessons,
  public.skills, public.reminders, public.agent_runs to service_role;

revoke execute on function public.match_messages, public.match_memories from public, anon, authenticated;
grant execute on function public.match_messages, public.match_memories to service_role;
