-- Выполните целиком в Supabase: SQL Editor -> New query -> Run
create table if not exists public.app_state (
  id text primary key,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.app_state enable row level security;
drop policy if exists "read for everyone" on public.app_state;
drop policy if exists "dispatchers update" on public.app_state;
drop policy if exists "dispatchers insert" on public.app_state;
create policy "read for everyone" on public.app_state for select to anon, authenticated using (true);
create policy "dispatchers update" on public.app_state for update to authenticated using (true) with check (true);
create policy "dispatchers insert" on public.app_state for insert to authenticated with check (true);
insert into public.app_state (id, data) values ('main', '{}'::jsonb) on conflict (id) do nothing;


-- Обращения пассажиров: отправка из формы сайта и просмотр диспетчерами.
create table if not exists public.report_submissions (
  id uuid primary key default gen_random_uuid(),
  route text not null default '',
  stop text not null default '',
  description text not null,
  created_at timestamptz not null default now(),
  status text not null default 'new' check (status in ('new','done'))
);
alter table public.report_submissions enable row level security;
drop policy if exists "public can submit reports" on public.report_submissions;
drop policy if exists "dispatchers can read reports" on public.report_submissions;
drop policy if exists "dispatchers can update reports" on public.report_submissions;
create policy "public can submit reports" on public.report_submissions
  for insert to anon, authenticated with check (char_length(description) between 1 and 5000);
create policy "dispatchers can read reports" on public.report_submissions
  for select to authenticated using (true);
create policy "dispatchers can update reports" on public.report_submissions
  for update to authenticated using (true) with check (status in ('new','done'));
