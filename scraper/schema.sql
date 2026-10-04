-- Supabase SQL Editor'da bir kez çalıştırılır. Tekrar çalıştırmak güvenlidir (idempotent).

-- 1) Tablo: kısıtlar Pydantic kurallarının veritabanı tarafındaki kopyasıdır (defense in depth)
create table if not exists public.jobs (
  dedup_hash    text primary key check (dedup_hash ~ '^[0-9a-f]{64}$'),
  source        text not null check (source ~ '^[a-z]{1,20}$'),
  company       text not null check (char_length(company) between 1 and 100),
  title         text not null check (char_length(title) between 1 and 300),
  url           text not null check (url ~ '^https://' and char_length(url) <= 2083),
  location      text check (char_length(location) <= 200),
  country       text check (country ~ '^[A-Z]{2}$'),
  posted_at     timestamptz,
  is_long_term  boolean not null default false,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now()  -- ilan hâlâ yayında mı? (Faz 5 filtresi)
);

-- Sonradan eklenen kolonlar (var olan tabloya da uygulanır)
alter table public.jobs add column if not exists is_new_grad boolean not null default false;

-- 2) RLS: anon (frontend) yalnızca okur. service_role RLS'i bypass eder, politika gerekmez.
alter table public.jobs enable row level security;

drop policy if exists "public read" on public.jobs;
create policy "public read" on public.jobs for select to anon, authenticated using (true);

-- Supabase varsayılan olarak anon'a tüm yetkileri verir; RLS zaten engeller, bu ikinci kilit
revoke insert, update, delete, truncate on public.jobs from anon, authenticated;

-- 3) Idempotent yazma: yeni ilan eklenir, var olan güncellenir. Yalnızca İLK KEZ görülenlerin hash'i döner.
create or replace function public.upsert_jobs(payload jsonb)
returns table (new_hash text)
language sql
security invoker
set search_path = ''
as $$
  with up as (
    insert into public.jobs as j
      (dedup_hash, source, company, title, url, location, country, posted_at, is_long_term, is_new_grad)
    select r.dedup_hash, r.source, r.company, r.title, r.url, r.location, r.country, r.posted_at, r.is_long_term,
           coalesce(r.is_new_grad, false)
    from jsonb_to_recordset(payload) as r(
      dedup_hash text, source text, company text, title text, url text,
      location text, country text, posted_at timestamptz, is_long_term boolean, is_new_grad boolean)
    on conflict (dedup_hash) do update
      set title = excluded.title,
          location = excluded.location,
          is_long_term = excluded.is_long_term,
          is_new_grad = excluded.is_new_grad,
          last_seen_at = now()
    returning j.dedup_hash, j.first_seen_at
  )
  -- yeni satırda first_seen_at = bu transaction'ın now()'ı; eski satırda daha eski bir zaman
  select up.dedup_hash from up where up.first_seen_at = now();
$$;

revoke execute on function public.upsert_jobs(jsonb) from public, anon, authenticated;
grant execute on function public.upsert_jobs(jsonb) to service_role;
