# Kairo Control Plane

The control plane owns Kairo's PostgreSQL schema, migrations, and typed database access. It does not start automatically or apply migrations during application startup.

## Database foundation

The database layer lives in `src/db`:

- `schema.ts` — Drizzle tables, enums, indexes, and constraints for users, organizations, memberships, and agents.
- `config.ts` — environment variable validation using TypeBox.
- `client.ts` — reusable, closable Drizzle/postgres.js connection factory and connection check.

`DATABASE_SCHEMA` is optional. When set, the connection uses it as the first entry in PostgreSQL's `search_path`.

## Local PostgreSQL

The root Compose file provides PostgreSQL 17 with settings matching the root `.env.example`. Start it with `pnpm run dev:up` from the repository root. To use an existing PostgreSQL 14+ instance instead, create the role and database yourself:

```sql
create role kairo login password 'change-me' createdb;
create database kairo owner kairo;
```

Copy the root `.env.example` to `.env` and set `DATABASE_URL` to that database. Tests require `TEST_DATABASE_URL`; the test role needs `CREATEDB` because each test file creates and drops a disposable database.

## Migration workflow

Run these from `apps/control-plane`:

```sh
pnpm db:generate
pnpm db:migrate
pnpm db:check
pnpm db:studio
```

`db:generate` creates versioned SQL migrations in `drizzle/`, which are committed to the repository. `db:migrate` applies them through the shared connection module and produces a redacted connection-failure message when PostgreSQL is unavailable. `db:check` validates migration consistency where Drizzle Kit supports it. `db:studio` opens Drizzle Studio for local inspection.

## Tests

```sh
TEST_DATABASE_URL=postgresql://kairo:change-me@localhost:5432/kairo pnpm test
```

The integration tests use real PostgreSQL. They verify connectivity, migration-created tables, foreign keys, membership uniqueness, agent/organization relationships, safe deletion behavior, and basic CRUD. No SQLite substitute is used.
