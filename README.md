# space-mcp

MCP server for reading merge request information from JetBrains Space.

## Requirements

- Python >= 3.11
- JetBrains Space account with API token

## Installation

```bash
pip install -e .
```

## Configuration

Set the `SPACE_TOKEN` environment variable with your JetBrains Space personal token:

```bash
export SPACE_TOKEN="your-token-here"
```

To get a token:
1. Go to https://jetbrains.team (or your Space instance)
2. Click your profile -> Preferences -> Personal Tokens
3. Create a new token with `Read code reviews` permission

## Available Tools

### get_merge_request

Get details of a specific merge request.

**Parameters:**
- `project` (string): Project key (e.g., "ij" for IntelliJ)
- `repository` (string): Repository name (e.g., "ultimate")
- `review_id` (string): Review/MR identifier (numeric ID)

**Returns:** JSON with title, state, author, reviewers, branches, and participants.

### get_merge_request_discussions

Get all comments, discussions, and timeline messages on a merge request.

Returns both code discussions (with file/line context) and general timeline
messages (including bot messages like Patronus dry run results).

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `review_id` (string): Review/MR identifier

**Returns:** JSON array of items, each with a `type` field:
- `"code_discussion"`: has `file`, `line`, `resolved`, `comments`
- `"message"`: has `text`, `author`, `created` (general timeline messages)

### list_merge_requests

List merge requests for a repository with optional filtering.

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `branch` (string, optional): Filter by source branch name
- `state` (string, optional): Filter by state - "Open", "Closed", or "Merged"
- `limit` (int, default=20): Maximum number of results

**Returns:** JSON array of MRs with id, title, state, author, and branches.

### find_merge_request_by_branch

Find a merge request for a specific branch.

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `branch` (string): Source branch name (e.g., "azhukova/QD-13281")
- `state` (string, optional): Filter by state - "Open", "Closed", or "Merged". Searches all states if not specified.

**Returns:** JSON with MR details if found, or null if no MR exists.

### get_patronus_robots

Find Patronus robots (dry runs / safe merges) for a branch.

**Parameters:**
- `repository` (string): Repository name (e.g., "ultimate")
- `source_branch` (string): Source branch name
- `target_branch` (string, optional): Target branch filter (e.g., "master")

**Returns:** JSON array of robots with id, name, status, pushMode, branches, and timestamps.
Status is one of: RUNNING, FAILING, SUCCESSFUL, FAILED, CANCELED.

### get_patronus_robot_details

Get details of a specific Patronus robot including TeamCity build checks and problems.

**Parameters:**
- `robot_id` (string): Patronus robot UUID (from `get_patronus_robots` or a Patronus URL)

**Returns:** JSON with `robot` (overview), `teamcity_checks` (build statuses/URLs), and `problems`.
The returned TeamCity build IDs can be inspected with `teamcity run view <build-id>`.

## Usage with Claude Code

Add to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "space": {
      "command": "space-mcp",
      "env": {
        "SPACE_TOKEN": "your-token-here"
      }
    }
  }
}
```

Or if installed in a specific location:

```json
{
  "mcpServers": {
    "space": {
      "command": "/path/to/venv/bin/space-mcp",
      "env": {
        "SPACE_TOKEN": "your-token-here"
      }
    }
  }
}
```

## Examples

Find your open MR by branch name:
```
find_merge_request_by_branch(project="ij", repository="ultimate", branch="azhukova/my-feature")
```

List all open MRs in a repository:
```
list_merge_requests(project="ij", repository="ultimate", state="Open")
```

Get discussions on a specific MR (includes code comments and timeline messages):
```
get_merge_request_discussions(project="ij", repository="ultimate", review_id="123456")
```

Find Patronus dry runs for a branch:
```
get_patronus_robots(repository="ultimate", source_branch="azhukova/my-feature")
```

Get Patronus robot details with TeamCity build checks:
```
get_patronus_robot_details(robot_id="cc448634-880e-411f-9ee6-347e9a6087ac")
```

## License

MIT License - Copyright 2026 Anna Zhukova
