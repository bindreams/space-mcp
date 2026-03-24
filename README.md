# Space MCP

MCP server and CLI for [JetBrains Space](https://www.jetbrains.com/space/) merge requests and [Patronus](https://patronus.labs.jb.gg) CI dry runs.

## Installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
uv tool install git+https://github.com/bindreams/space-mcp.git
```

This installs two entry points:

| Command     | Purpose                                   |
| ----------- | ----------------------------------------- |
| `space`     | CLI for merge requests, CI runs, and auth |
| `space-mcp` | MCP server (stdio transport)              |

## Authentication

A JetBrains Space personal token is required.
Generate one at [Personal Tokens](https://jetbrains.team/m/me/authentication?tab=PermanentTokens).

Token is resolved in order:

1. `SPACE_TOKEN` environment variable
2. OS keyring (stored via `space auth login`)
3. `~/.config/space/credentials.json` (plaintext fallback)

```sh
space auth login              # store token in keyring (prompted)
space auth login --token PAT  # non-interactive
space auth status             # show token source and detected context
space auth logout             # remove stored credentials
```

During login you will also be offered to authenticate Docker with `registry.jetbrains.team`.

## MCP Tools

| Tool                            | Description                                                | Parameters                                                                         |
| ------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `get_merge_request`             | Get MR details (title, state, author, reviewers)           | `project`, `repository`, `review_id`                                               |
| `list_merge_requests`           | List MRs for a repository                                  | `project`, `repository`, `branch?`, `state?`, `limit?`                             |
| `find_merge_request_by_branch`  | Find MR by source branch name                              | `project`, `repository`, `branch`, `state?`                                        |
| `create_merge_request`          | Create a new merge request                                 | `project`, `repository`, `source_branch`, `target_branch`, `title`, `description?` |
| `close_merge_request`           | Close a merge request                                      | `project`, `review_id`                                                             |
| `reopen_merge_request`          | Reopen a closed merge request                              | `project`, `review_id`                                                             |
| `get_merge_request_discussions` | Full MR timeline: comments, reviews, dry run results       | `project`, `repository`, `review_id`                                               |
| `download_attachment`           | Download a file attachment from MR discussion              | `attachment_id`                                                                    |
| `get_patronus_robots`           | List Patronus robots (dry runs / safe merges) for an MR    | `project`, `review_id`                                                             |
| `get_patronus_robot_details`    | Robot details with TeamCity checks and problems            | `robot_id`                                                                         |
| `start_patronus_dry_run`        | Start a CI dry run for an MR                               | `project`, `review_id`                                                             |
| `cancel_patronus_robot`         | Cancel a running robot                                     | `robot_id`                                                                         |

All tools return Markdown. Parameters marked with `?` are optional.

### MCP server configuration

First, authenticate via the CLI — the MCP server picks up stored credentials automatically:

```sh
space auth login
```

Then add to `.mcp.json` (project) or `~/.claude.json` (global):

```json
{
  "mcpServers": {
    "space": {
      "command": "space-mcp"
    }
  }
}
```

## CLI

Global options: `-P/--project`, `-R/--repo`, `--json`, `--no-color`.
Project and repo are auto-detected from the git remote when inside a Space repository.

### `space mr` — Merge requests

```
space mr view [REF]        # MR details (number, URL, branch, or current branch)
space mr list              # list MRs (-s open|closed|merged|all, -A author, -H branch)
space mr create BRANCH     # create MR from branch (-t title, -b base, -d description)
space mr close [REF]       # close an MR
space mr reopen [REF]      # reopen a closed MR
space mr timeline [REF]    # full timeline with discussions and dry run results
space mr checks [REF]      # Patronus CI check status (--watch to poll)
space mr diff [REF]        # diff between target and source (--stat, --name-only)
space mr checkout [REF]    # fetch and checkout the MR branch
space mr merge [REF]       # safe merge via Patronus (--rebase, --squash, --dry-run)
space mr download ID       # download attachment by ID (-o output path)
```

### `space run` — Patronus CI runs

```
space run list            # list runs for current branch (-b branch, -B base)
space run view ROBOT      # run details with TeamCity checks (UUID or URL)
space run start [REF]     # start dry run (--merge, --rebase, --squash, --watch)
space run cancel ROBOT    # cancel a running robot
space run watch ROBOT     # live progress with terminal animation
```

### `space auth` — Authentication

```
space auth login          # store token (--token, --insecure-storage)
space auth logout         # remove credentials
space auth status         # show token source and context
```

### `space api` — Raw API access

```
space api /api/http/...                   # authenticated GET to Space
space api /app/rest/... --patronus        # authenticated GET to Patronus
space api /api/http/... -X POST -f key=val  # POST with JSON body
```

### `space status` — Dashboard

```
space status              # MR and latest CI run for current branch
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and testing.

## License
Copyright 2026, Anna Zhukova

This project is licensed under MPL-2.0. The license text can be found at [LICENSE.md](/LICENSE.md).
