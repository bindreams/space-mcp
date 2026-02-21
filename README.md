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

Get all comments and discussions on a merge request.

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `review_id` (string): Review/MR identifier

**Returns:** JSON array of discussions with author, text, file/line context, and replies.

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

Find an open merge request for a specific branch.

**Parameters:**
- `project` (string): Project key
- `repository` (string): Repository name
- `branch` (string): Source branch name (e.g., "azhukova/QD-13281")

**Returns:** JSON with MR details if found, or null if no open MR exists.

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

Get discussions on a specific MR:
```
get_merge_request_discussions(project="ij", repository="ultimate", review_id="123456")
```

## License

MIT License - Copyright 2026 Anna Zhukova
