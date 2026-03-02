# space

CLI and MCP server for JetBrains Space.

## Requirements

- Python >= 3.11
- JetBrains Space account with API token

## Configuration

Set the `SPACE_TOKEN` environment variable with your JetBrains Space personal token:

```bash
export SPACE_TOKEN="your-token-here"
```

To get a token:
1. Go to https://jetbrains.team (or your Space instance)
2. Click your profile -> Preferences -> Personal Tokens
3. Create a new token with `Read code reviews` permission

## Usage with Claude Code

From a git repo (recommended):

```json
{
  "mcpServers": {
    "space": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bindreams/space-mcp", "space-mcp"],
      "env": {
        "SPACE_TOKEN": "your-token-here"
      }
    }
  }
}
```

From a local checkout:

```json
{
  "mcpServers": {
    "space": {
      "command": "uvx",
      "args": ["--from", "/path/to/space-mcp", "space-mcp"],
      "env": {
        "SPACE_TOKEN": "your-token-here"
      }
    }
  }
}
```

## Available Tools

### get_merge_request

Get details of a specific merge request.

**Parameters:**
- `project` (string): Project key (e.g., "ij" for IntelliJ)
- `repository` (string): Repository name (e.g., "ultimate")
- `review_id` (string): Review/MR identifier (numeric ID)

**Returns:** Markdown with title, description, state, author, branches, and reviewer table.

### get_merge_request_discussions

Get the full timeline of a merge request: comments, dry runs, commits, reviews.

Returns a chronological markdown timeline with day sections, threaded replies
(Patronus dry run results, safe merge status), and code review discussions.

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `review_id` (string): Review/MR identifier

**Returns:** Markdown timeline grouped by day, with threaded replies indented.

### list_merge_requests

List merge requests for a repository with optional filtering.

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `branch` (string, optional): Filter by source branch name
- `state` (string, optional): Filter by state - "Open", "Closed", or "Merged"
- `limit` (int, default=20): Maximum number of results

**Returns:** Markdown table of merge requests.

### find_merge_request_by_branch

Find a merge request for a specific branch.

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `branch` (string): Source branch name (e.g., "azhukova/QD-13281")
- `state` (string, optional): Filter by state - "Open", "Closed", or "Merged". Searches all states if not specified.

**Returns:** Markdown with MR details if found, or "No merge request found."

### get_patronus_robots

Find Patronus robots (dry runs / safe merges) for a branch.

**Parameters:**
- `repository` (string): Repository name (e.g., "ultimate")
- `source_branch` (string): Source branch name
- `target_branch` (string, optional): Target branch filter (e.g., "master")

**Returns:** Markdown table of robots with IDs for follow-up queries.

### get_patronus_robot_details

Get details of a specific Patronus robot including TeamCity build checks and problems.

**Parameters:**
- `robot_id` (string): Patronus robot UUID (from `get_patronus_robots` or a Patronus URL)

**Returns:** Markdown with robot overview, TeamCity checks table, and problems.
The returned TeamCity build IDs can be inspected with `teamcity run view <build-id>`.

## Examples

Find your open MR by branch name:
```
find_merge_request_by_branch(project="ij", repository="ultimate", branch="azhukova/my-feature")
```

List all open MRs in a repository:
```
list_merge_requests(project="ij", repository="ultimate", state="Open")
```

Get the full timeline of an MR (includes code comments, dry runs, reviews):
```
get_merge_request_discussions(project="ij", repository="ultimate", review_id="188120")
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
