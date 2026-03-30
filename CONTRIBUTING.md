# Contributing

## Development setup

```sh
git clone https://git.jetbrains.team/space-mcp/space-mcp.git
cd space-mcp
uv sync --group dev --group test
```

## Running tests

```sh
# Unit tests (no API access needed)
uv run --group test pytest tests/ -m "not e2e"

# E2E tests (requires SPACE_TOKEN in .env)
uv run --group test pytest tests/ -m e2e

# E2E tests excluding those that need a personal access token
uv run --group test pytest tests/ -m "e2e and not user_token"
```

## Code style

This project uses [yapf](https://github.com/google/yapf) for formatting. Pre-commit hooks run automatically via `prek`. To run manually:

```sh
prek run --files <files...>
```

Checks: yapf formatting, section comment style, ty type checker, mdformat, editorconfig.

## Credentials

### `.env` file

Create a `.env` file in the project root:

```
SPACE_TOKEN="<Space Application token>"
PATRONUS_URL="https://patronus-staging.labs.jb.gg"
```

| Variable           | Purpose                                | Required                                          |
| ------------------ | -------------------------------------- | ------------------------------------------------- |
| `SPACE_TOKEN`      | Space Application token for API access | Yes (e2e)                                         |
| `PATRONUS_URL`     | Patronus instance URL                  | Yes (e2e) — must be **staging**, never production |
| `SPACE_USER_TOKEN` | Personal access token with email       | Only for `@pytest.mark.user_token` tests          |

### Space MCP Bot

The `SPACE_TOKEN` should be a **Space Application token** (not a personal token) to avoid test actions appearing in a person's MR history. The application is called "Space MCP Bot" in the SPACE-MCP Space project.

## Test repositories

### `test` (`space-mcp/test`)

General-purpose test repo for MR lifecycle tests (create, close, reopen, merge), timeline/discussion tests, and MCP formatting tests. Branches named `test/*` are created and deleted automatically.

### `test-patronus` (`space-mcp/test-patronus`)

Patronus CI integration tests. This repo has additional infrastructure:

**Files on `main`** (protected — requires admin access to push):

| File                     | Purpose                                                  |
| ------------------------ | -------------------------------------------------------- |
| `.patronus/config.yaml`  | Lists TeamCity build configs for Patronus to run         |
| `.space/safe-merge.yaml` | Configures Patronus (staging) as the safe-merge executor |
| `.space.kts`             | Space Automation job (not used by safe-merge currently)  |

**Space project secrets** at https://jetbrains.team/p/space-mcp/parameters:

| Secret                                    | Purpose                                             |
| ----------------------------------------- | --------------------------------------------------- |
| `safe.merge.patronus.starter.space.token` | Patronus app token for Space→Patronus communication |

**TeamCity** at https://buildserver.labs.intellij.net:

| Resource     | ID / Location                              |
| ------------ | ------------------------------------------ |
| Project      | `Sandbox_AnnaZhukova`                      |
| Build config | `Sandbox_AnnaZhukova_SpaceMcpCheck`        |
| VCS root     | `Sandbox_AnnaZhukova_SpaceMcpTestPatronus` |

The build config runs a shell script that checks for a `FAIL_CI` marker file. If present, it reports a test failure via TeamCity service messages and exits 1. This lets e2e tests control whether a dry run passes or fails.

Key TeamCity requirements:

- VCS root branch spec must include `+:(refs/patronus/*)` — parentheses required for nested paths
- A VCS trigger must exist (otherwise TC marks the VCS root as `not_monitored`)
- VCS root auth: PASSWORD with `username=x-oauth-basic`, `password=%space.mcp.bot.token%`
- The Patronus TC user (ID 7030) needs the `Patronus: Orchestration` role on the project

### How the Patronus e2e tests work

1. `ensure_repo_ready()` verifies `main` has required config files and safe-merge is linked
1. `_start_dry_run()` creates a test branch, optionally pushes a `FAIL_CI` marker, creates an MR, starts a dry run
1. Space delegates to Patronus (staging), which triggers the TC build
1. TC checks for `FAIL_CI` — if present, reports a test failure and exits 1
1. Patronus marks the run as FAILURE
1. Tests assert on run status, checks, and attempt details

### Troubleshooting

**"Dry run not found after 120s"**:

- Check `PATRONUS_URL` in `.env` is staging (`https://patronus-staging.labs.jb.gg`)
- Check TC build config has a VCS trigger and `+:(refs/patronus/*)` in branch spec
- Check Patronus TC user has the Orchestration role on the Sandbox project

**Thread reply tests fail**:

- `post_comment` uses `channel=message:{id}` for thread replies — a `thread` parameter does NOT work (silently ignored by the Space API)

## Git credential isolation

All tests run with git credential helpers disabled (`GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`) to prevent token leakage into the system keychain.

If your git operations to `git.jetbrains.team` use wrong credentials after running tests, clear cached credentials:

```sh
# macOS Keychain
git credential-osxkeychain erase <<EOF
protocol=https
host=git.jetbrains.team
EOF

# Git Credential Manager
git-credential-manager erase <<EOF
protocol=https
host=git.jetbrains.team
EOF
```
