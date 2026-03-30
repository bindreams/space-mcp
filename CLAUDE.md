# space-mcp

MCP server and CLI for JetBrains Space (merge requests, code reviews) and Patronus (CI dry runs, safe merges).

## API References

### Space HTTP API

- **API Playground** (interactive, requires auth): `https://jetbrains.team/extensions/httpApiPlayground`
- **Public docs**: https://www.jetbrains.com/help/space/api.html
- **Generated SDK with full type definitions**: https://github.com/JetBrains/space-dotnet-sdk
  - DTOs: `src/JetBrains.Space.Client/Generated/Dtos/`
  - Enums: `src/JetBrains.Space.Client/Generated/Enums/`
  - This is the most reliable source for request/response schemas (auto-generated from the Space API model).

Key endpoints used:

- `GET /api/http/projects/key:{project}/code-reviews/{id}` — get MR
- `GET /api/http/projects/key:{project}/code-reviews` — list MRs
- `POST /api/http/projects/key:{project}/code-reviews/safe-merge` — start dry run / merge
- `GET /api/http/chats/messages` — timeline / discussions
- `POST /api/http/chats/messages/send-message` — post comments / replies
- `POST /api/http/projects/key:{project}/code-reviews/code-discussions` — create inline code discussions (reviewId in body)

### Patronus REST API

- **Docs**: https://youtrack.jetbrains.com/articles/PAT-A-11/REST-API
- **Base URL**: `https://patronus.labs.jb.gg`
- Uses the same Space bearer token for auth via `/app/rest/` prefix.
- **Important**: the `/app/rest/v1/robots/space-safe-merge` endpoint is only for Space-to-Patronus integration. To start dry runs, use the Space safe-merge API above, not the Patronus API directly.

Key endpoints used:

- `GET /app/rest/v1/robots` — list runs
- `GET /app/rest/v1/robots/{id}` — run details
- `GET /app/rest/v1/robots/{id}/teamcity-checks` — TC build checks
- `GET /app/rest/v1/robots/{id}/problems` — run problems
- `GET /app/rest/v1/robots/{id}/changes` — run changes (commits)
- `PUT /app/rest/v1/robots/{id}/cancel` — cancel run

### MergeSelectOptions schema (Space safe-merge)

The `mergeOptions` body for the safe-merge endpoint requires all of these fields:

```
operation:        MergeSelectOptionsOperation — DryRun | Merge | Rebase
mergeMode:        GitMergeMode               — FF | FF_ONLY | NO_FF
rebaseMode:       GitRebaseMode              — FF | NO_FF
squashMode:       GitSquashMode              — ALL | AUTO | NONE
squashCommitMessage: string                  — required (can be empty)
deleteSourceBranch:  bool
targetStatusesForLinkedIssues: list
```

Source: `JetBrains/space-dotnet-sdk` generated DTOs and enums.

## Project structure

```
src/space/
  auth.py          — Token resolution, keyring/file credential storage
  client.py        — SpaceClient (Space HTTP API)
  clients.py       — Client factory (lazy init, token resolution)
  context.py       — Git context inference (project, repo, branch from remote)
  discussions.py   — Timeline/discussion fetching for merge requests
  formatting.py    — Shared formatting utilities (human_size)
  pagination.py    — Overlap-based paginated fetch with consistency verification
  patronus.py      — PatronusClient (Patronus REST API)
  __main__.py      — CLI entry point (click)
  models/          — Frozen dataclass domain models
    enums.py       — StrEnum definitions (MRState, RunStatus, PushMode, etc.)
    space.py       — SpacePrincipal, SpaceAccount, SpaceApp, MergeRequest, timeline items
    patronus.py    — PatronusRun, PatronusCheckRun, AttemptDetails, Problem
    status.py      — Derived display status (effective_status)
  cli/             — CLI commands
    app.py         — CliState, async_command, resolve_mr
    mr.py          — MR read commands (view, list, timeline, checks)
    mr_actions.py  — MR action commands (create, close, reopen, merge, checkout, diff, download)
    run.py, auth.py, status.py, api.py, format.py
  mcp/
    base.py        — MCP base class with @mcptool decorator and auto error handling
    server.py      — SpaceMCP class (MCP tool definitions)
    format.py      — YAML/Markdown formatters for MCP responses
    yaml_utils.py  — YAML serialization utility (dump_yaml)
```

## Running

- **MCP server**: `space-mcp` or `python -m space.mcp`
- **CLI**: `space <command>` (e.g., `space mr list`, `space run start`)
- **Unit tests**: `uv run --group test pytest tests/ -m "not e2e"`
- **E2E tests** (requires SPACE_TOKEN): `uv run --group test pytest tests/ -m e2e`
- **All tests**: `uv run --group test pytest tests/`

## Auth

Token resolution order: `SPACE_TOKEN` env var > OS keyring > `~/.config/space/credentials.json`.

The MCP server uses the same `resolve_token()` path — no separate env var needed. Run `space auth login` to store credentials in the keyring.

Both personal access tokens and Space Application tokens are supported:

- `validate_token()` returns `{"kind": "user", "username": ..., "emails": [...]}` for personal tokens
  and `{"kind": "app", "name": ...}` for application tokens.
- `space auth login` and `space auth status` display the appropriate identity for both token types.
- `SpaceAccount.from_inline` provides graceful fallback when the team directory is inaccessible
  (app tokens can't resolve user profiles — inline data from API responses is used instead).

E2E tests use `SPACE_TOKEN` (loaded from `.env` by pytest-dotenv). Use a Space Application token
to avoid test actions appearing in personal MR history.

`SPACE_USER_TOKEN` (optional) — a personal access token with email, needed for git credential
tests (`@pytest.mark.user_token`). Skip these with `-m "not user_token"` if unavailable.
