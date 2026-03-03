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

### Patronus REST API

- **Docs**: https://youtrack.jetbrains.com/articles/PAT-A-11/REST-API
- **Base URL**: `https://patronus.labs.jb.gg`
- Uses the same Space bearer token for auth via `/app/rest/` prefix.
- **Important**: the `/app/rest/v1/robots/space-safe-merge` endpoint is only for Space-to-Patronus integration. To start dry runs, use the Space safe-merge API above, not the Patronus API directly.

Key endpoints used:
- `GET /app/rest/v1/robots` — list robots
- `GET /app/rest/v1/robots/{id}` — robot details
- `GET /app/rest/v1/robots/{id}/teamcity-checks` — TC build checks
- `GET /app/rest/v1/robots/{id}/problems` — robot problems
- `PUT /app/rest/v1/robots/{id}/cancel` — cancel robot

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
  client.py        — SpaceClient (Space HTTP API)
  patronus.py      — PatronusClient (Patronus REST API)
  clients.py       — Client factory (lazy init, token resolution)
  context.py       — Git context inference, auth token resolution (env > keyring > file)
  __main__.py      — CLI entry point (click)
  cli/             — CLI commands (mr, run, auth, api, status)
  mcp/
    server.py      — MCP tool definitions
    format.py      — Markdown formatters for MCP responses
```

## Running

- **MCP server**: `space-mcp` or `python -m space.mcp`
- **CLI**: `space <command>` (e.g., `space mr list`, `space run start`)
- **Tests**: `uv run --group test pytest tests/ --ignore=tests/test_integration.py`

## Auth

Token resolution order: `SPACE_TOKEN` env var > OS keyring > `~/.config/space/credentials.json`.

The MCP server uses the same `resolve_token()` path — no separate env var needed. Run `space auth login` to store credentials in the keyring.
