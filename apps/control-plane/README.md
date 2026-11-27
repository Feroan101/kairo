# Kairo Control Plane

The control plane owns Kairo's PostgreSQL schema, migrations, typed database access, and REST API. It does not apply migrations during application startup.

## HTTP API

Start the API with `pnpm start` from this directory after applying migrations. `HOST` (default `127.0.0.1`), `PORT` (default `3000`), `SESSION_TTL_SECONDS` (default `604800`), and `LOG_LEVEL` (default `info`) configure the server.

Identity and access routes:

| Method | Path | Access |
| --- | --- | --- |
| `POST` | `/v1/auth/register` | public |
| `POST` | `/v1/auth/login` | public |
| `GET` | `/v1/auth/me` | authenticated |
| `GET` | `/v1/auth/sessions` | authenticated |
| `DELETE` | `/v1/auth/sessions/:sessionId` | authenticated, own sessions |
| `POST` | `/v1/auth/logout` | authenticated |
| `POST` | `/v1/organizations` | authenticated |
| `GET` | `/v1/organizations` | authenticated, member-scoped |
| `GET` | `/v1/organizations/:organizationId` | organization member |
| `GET` | `/v1/organizations/:organizationId/members` | organization member |
| `POST` | `/v1/organizations/:organizationId/members` | organization admin |
| `PATCH` / `DELETE` | `/v1/organizations/:organizationId/members/:userId` | organization admin |

Agent management routes:

| Method | Path | Access |
| --- | --- | --- |
| `POST` | `/v1/organizations/:organizationId/agents` | organization member |
| `GET` | `/v1/organizations/:organizationId/agents` | organization member |
| `GET` | `/v1/organizations/:organizationId/agents/:agentId` | organization member |
| `PATCH` | `/v1/organizations/:organizationId/agents/:agentId` | agent creator or organization admin |
| `PATCH` | `/v1/organizations/:organizationId/agents/:agentId/status` | agent creator or organization admin |
| `DELETE` | `/v1/organizations/:organizationId/agents/:agentId` | agent creator or organization admin |

Authenticated routes use `Authorization: Bearer <token>`. Passwords are hashed with scrypt, session tokens are stored only as SHA-256 hashes, and authorization failures are denied by default. The last owner of an organization cannot be demoted or removed. `GET /health` and `GET /openapi.json` are public.

## Database foundation

The database layer lives in `src/db`:

- `schema.ts` — Drizzle tables, enums, indexes, and constraints for users, credentials, sessions, audit events, organizations, memberships, and agents.
- `config.ts` — database environment variable validation using TypeBox.
- `client.ts` — reusable, closable Drizzle/postgres.js connection factory and connection check.

The HTTP layer lives in `src/app.ts`, `src/server.ts`, `src/errors.ts`, `src/identity/`, and `src/agents/`. Fastify plugins, TypeBox schemas, and generated OpenAPI keep request validation, error responses, and organization boundaries in one module.

Agent configurations store provider and model identifiers, harness version, model settings, tool permissions, granted permissions, execution policies, and memory scope. Credentials are never part of agent configuration; secret-shaped keys are rejected by API validation and the PostgreSQL configuration constraint. `DELETE` archives an agent instead of removing its durable identity.

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

The integration tests use real PostgreSQL. They verify connectivity, migration-created tables, foreign keys, membership uniqueness, agent/organization relationships, safe deletion behavior, basic CRUD, authentication, session revocation, organization isolation, role enforcement, and audit recording. `test/identity-units.test.ts` covers password hashing, token generation, role ranking, and server configuration without a database. No SQLite substitute is used.
