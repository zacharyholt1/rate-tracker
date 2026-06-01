-- Supabase schema for Rate Tracker.
-- Apply via the Supabase SQL editor (or `supabase db push`).

-- Staging area for user-submitted sources. scrape_url writes here with
-- status 'pending'; nothing reaches live data until reviewed and promoted
-- through the validated Python pipeline.
create table if not exists public.submissions (
  id            uuid primary key default gen_random_uuid(),
  url           text not null,
  host          text not null,
  content_hash  text not null,
  raw_excerpt   text,
  content_type  text,
  submitted_by  uuid references auth.users (id),
  status        text not null default 'pending'
                check (status in ('pending', 'promoted', 'rejected')),
  created_at    timestamptz not null default now()
);

-- Row-Level Security: deny-all by default, then open up explicitly.
alter table public.submissions enable row level security;

-- A signed-in user may insert a submission, and only as themselves.
create policy "users insert own submissions"
  on public.submissions for insert
  to authenticated
  with check (submitted_by = auth.uid());

-- A user may read back only their own submissions.
create policy "users read own submissions"
  on public.submissions for select
  to authenticated
  using (submitted_by = auth.uid());

-- Note: the scrape_url function uses the service-role key, which bypasses RLS.
-- Review/promotion is an admin action performed out-of-band. No update/delete
-- policies are granted to normal users, so they cannot alter or remove rows.
