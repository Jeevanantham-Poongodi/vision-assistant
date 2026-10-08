create extension if not exists "pgcrypto";

create table app_users (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  role        text not null check (role in ('user', 'guardian')),
  phone       text,
  created_at  timestamptz not null default now()
);

create table guardian_links (
  guardian_id uuid not null references app_users(id) on delete cascade,
  user_id     uuid not null references app_users(id) on delete cascade,
  relation    text,
  created_at  timestamptz not null default now(),
  primary key (guardian_id, user_id)
);

create table sessions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references app_users(id) on delete cascade,
  status       text not null default 'active' check (status in ('active', 'ended')),
  device_info  jsonb not null default '{}'::jsonb,
  started_at   timestamptz not null default now(),
  ended_at     timestamptz
);
create index sessions_user_status_idx on sessions (user_id, status);

create table alerts (
  id               uuid primary key default gen_random_uuid(),
  session_id       uuid references sessions(id) on delete set null,
  user_id          uuid not null references app_users(id) on delete cascade,
  type             text not null check (type in ('hazard', 'emergency', 'assistance_request', 'system')),
  risk_level       text not null check (risk_level in ('critical', 'high', 'medium', 'low')),
  title            text not null,
  message          text not null,
  payload          jsonb not null default '{}'::jsonb,   -- e.g. the Detection that triggered it
  lat              double precision,
  lng              double precision,
  accuracy_m       real,
  status           text not null default 'open' check (status in ('open', 'acknowledged', 'resolved')),
  acknowledged_by  uuid references app_users(id),
  acknowledged_at  timestamptz,
  created_at       timestamptz not null default now()
);
create index alerts_session_created_idx on alerts (session_id, created_at desc);
create index alerts_status_idx on alerts (status);

create table location_pings (
  id          bigint generated always as identity primary key,
  session_id  uuid not null references sessions(id) on delete cascade,
  lat         double precision not null,
  lng         double precision not null,
  accuracy_m  real,
  heading_deg real,
  speed_mps   real,
  recorded_at timestamptz not null default now()
);
create index location_pings_session_idx on location_pings (session_id, recorded_at desc);

alter table app_users       enable row level security;
alter table guardian_links  enable row level security;
alter table sessions        enable row level security;
alter table alerts          enable row level security;
alter table location_pings  enable row level security;

-- Seed data (fixed IDs used by frontend mocks, Postman and the demo)
insert into app_users (id, name, role) values
  ('11111111-1111-1111-1111-111111111111', 'Arun', 'user'),
  ('22222222-2222-2222-2222-222222222222', 'Priya', 'guardian');
insert into guardian_links (guardian_id, user_id, relation) values
  ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'sister');
