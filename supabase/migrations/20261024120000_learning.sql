-- Stage 7: skills and self-learning.

-- The weekly lessons review is a recurring reminders row, like the morning brief.
alter table public.reminders drop constraint reminders_kind_check;
alter table public.reminders
  add constraint reminders_kind_check check (kind in ('reminder', 'brief', 'lessons_review'));

-- At most one active weekly review.
create unique index reminders_one_active_review on public.reminders (kind)
  where kind = 'lessons_review' and status = 'pending';

-- Skill names are looked up case-insensitively.
create unique index skills_name_lower_idx on public.skills (lower(name));
