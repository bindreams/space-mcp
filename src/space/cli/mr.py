"""space mr — Merge request commands."""

import subprocess
from typing import Any

import click

from .app import CliState, async_command, pass_state, resolve_mr
from . import format as fmt

_OPERATION_MAP = {
    "DRY_RUN": "DryRun",
    "MERGE": "Merge",
    "REBASE": "Rebase",
    "REBASE_AUTOSQUASH": "RebaseAutosquash",
    "REBASE_SQUASH_ALL": "RebaseSquashAll",
}


@click.group("mr", short_help="Manage merge requests (code reviews)")
def mr_group():
    """Manage JetBrains Space merge requests (code reviews).

    A merge request can be specified by number, URL, branch name,
    or omitted to use the current branch.
    """


# mr view =====================================================================


@mr_group.command("view")
@click.argument("mr_ref", required=False)
@click.option("-w", "--web", is_flag=True, help="Open in browser")
@pass_state
@async_command
async def mr_view(state: CliState, mr_ref: str | None, web: bool):
    """Display details of a merge request: title, state, branches, reviewers."""
    mr = await resolve_mr(state, mr_ref)

    if web:
        _open_mr_in_browser(mr)
        return

    if state.use_json:
        fmt.print_json(mr, state.json_fields)
        return

    _print_mr_details(mr)


def _open_mr_in_browser(mr: dict[str, Any]) -> None:
    """Open an MR in the browser."""
    number = mr.get("number", "")
    # Construct the URL from the MR's branch pair (to get the project)
    # For now, use a simple pattern
    url = f"https://jetbrains.team/p/ij/reviews/{number}/timeline"
    click.launch(url)


def _print_mr_details(mr: dict[str, Any]) -> None:
    """Print MR details in human-readable format."""
    number = mr.get("number", "?")
    title = mr.get("title", "Untitled")
    status = mr.get("state", "Unknown")

    click.secho(f"#{number} {title}", bold=True)
    click.echo(f"{fmt.styled_status(status)} — {fmt.extract_name(mr.get('createdBy', {}))}")

    for bp in mr.get("branchPairs", []):
        repo = bp.get("repository")
        repo_name = repo.get("name") if isinstance(repo, dict) else repo
        click.echo(f"{bp.get('sourceBranch')} → {bp.get('targetBranch')} ({repo_name})")

    description = mr.get("description")
    if description:
        click.echo()
        click.echo(description)

    # Reviewers -----
    participants = mr.get("participants", [])
    reviewers = [p for p in participants if p.get("role") != "Author"]
    if reviewers:
        click.echo()
        click.secho("Reviewers", bold=True)
        for p in reviewers:
            user = p.get("user", {})
            name = fmt.extract_name(user)
            rev_state = p.get("state")
            symbol = fmt.reviewer_symbol(rev_state)
            display_state = rev_state or "Pending"
            click.echo(f"  {symbol} {name} ({display_state})")


# mr list =====================================================================


@mr_group.command("list")
@click.option("-s", "--state", "state_filter",
              type=click.Choice(["open", "closed", "merged", "all"], case_sensitive=False),
              default="open", help="Filter by state (default: open)")
@click.option("-H", "--head", "head_branch", default=None, help="Filter by source branch")
@click.option("-A", "--author", default=None, help="Filter by author username")
@click.option("-L", "--limit", default=20, type=int, help="Max results (default: 20)")
@click.option("-w", "--web", is_flag=True, help="Open in browser")
@pass_state
@async_command
async def mr_list(state: CliState, state_filter: str, head_branch: str | None,
                  author: str | None, limit: int, web: bool):
    """List merge requests. Shows open MRs by default."""
    state_val = state_filter
    project = state.require_project()
    repo = state.require_repo()
    client = state.space_client()

    # Map CLI state names to API state names
    api_state = None
    if state_val and state_val != "all":
        api_state_map = {"open": "Open", "closed": "Closed", "merged": "Merged"}
        api_state = api_state_map.get(state_val.lower())

    reviews = await client.list_merge_requests(
        project=project, repository=repo, branch=head_branch,
        state=api_state, limit=limit,
    )

    # Client-side author filter
    if author:
        reviews = [
            r for r in reviews
            if (r.get("createdBy", {}).get("username") or "").lower() == author.lower()
        ]

    if state.use_json:
        fmt.print_json(reviews, state.json_fields)
        return

    if not reviews:
        click.echo("No merge requests found.")
        return

    headers = ["#", "TITLE", "STATE", "AUTHOR", "BRANCH"]
    rows = []
    for mr in reviews:
        title = mr.get("title", "?")
        mr_state = mr.get("state", "?")
        mr_author = fmt.extract_name(mr.get("createdBy", {}))
        branch = ""
        for bp in mr.get("branchPairs", []):
            branch = f"{bp.get('sourceBranch')} → {bp.get('targetBranch')}"
            break
        # Use id as fallback since list doesn't always return number
        number = str(mr.get("number", mr.get("id", "?")))
        rows.append([number, title, fmt.styled_status(mr_state), mr_author, branch])

    fmt.print_table(headers, rows, max_widths={1: 50, 4: 60})


# mr timeline =================================================================


@mr_group.command("timeline")
@click.argument("mr_ref", required=False)
@pass_state
@async_command
async def mr_timeline(state: CliState, mr_ref: str | None):
    """View the full timeline: comments, code discussions, reviews, dry run results."""
    mr = await resolve_mr(state, mr_ref)
    project = state.require_project()
    repo = state.require_repo()
    client = state.space_client()

    review_id = str(mr.get("number", mr.get("id")))
    items = await client.get_merge_request_discussions(project, repo, review_id)

    if state.use_json:
        fmt.print_json(items, state.json_fields)
        return

    if not items:
        click.echo("No timeline items.")
        return

    current_day = ""
    for item in items:
        item_type = item.get("type")

        if item_type == "code_discussion":
            first_ts = item.get("comments", [{}])[0].get("created") if item.get("comments") else None
            day = fmt.format_epoch_date(first_ts)
            if day and day != current_day:
                current_day = day
                click.echo()
                click.secho(day, bold=True)

            file_path = item.get("file", "?")
            line_num = item.get("line", "?")
            resolved = " [resolved]" if item.get("resolved") else ""
            comments = item.get("comments", [])
            if comments:
                first = comments[0]
                author_name = fmt.extract_author(first.get("author"))
                time_str = fmt.format_epoch_ms(first.get("created"))
                click.echo(f"  {author_name} ({time_str}) on {file_path}:{line_num}{resolved}")
                click.echo(f"    {first.get('text', '')}")
                for reply in comments[1:]:
                    reply_author = fmt.extract_author(reply.get("author"))
                    text = reply.get("text", "")
                    if text.startswith("User resolved the discussion"):
                        click.echo(f"    └ {reply_author}: resolved the discussion")
                    elif text.startswith("User reopened the discussion"):
                        click.echo(f"    └ {reply_author}: reopened the discussion")
                    else:
                        click.echo(f"    └ {reply_author}: {text}")

        elif item_type == "message":
            created = item.get("created")
            day = fmt.format_epoch_date(created)
            if day and day != current_day:
                current_day = day
                click.echo()
                click.secho(day, bold=True)

            author_name = fmt.extract_author(item.get("author"))
            time_str = fmt.format_epoch_ms(created)
            text = item.get("text", "")
            click.echo(f"  {author_name} ({time_str}): {text}")

            for reply in item.get("thread_replies", []):
                reply_author = fmt.extract_author(reply.get("author"))
                click.echo(f"    └ {reply_author}: {reply.get('text', '')}")


# mr checks ===================================================================


@mr_group.command("checks")
@click.argument("mr_ref", required=False)
@click.option("--watch", is_flag=True, help="Watch until all checks finish")
@click.option("-i", "--interval", default=10, type=int, help="Refresh interval in seconds (default: 10)")
@click.option("--fail-fast", is_flag=True, help="Exit on first failure")
@click.option("-w", "--web", is_flag=True, help="Open Patronus page in browser")
@pass_state
@async_command
async def mr_checks(state: CliState, mr_ref: str | None, watch: bool, interval: int, fail_fast: bool, web: bool):
    """Show Patronus CI check status for a merge request."""
    mr = await resolve_mr(state, mr_ref)
    repo = state.require_repo()
    patronus = state.patronus_client()

    # Find source branch from MR
    source_branch = None
    for bp in mr.get("branchPairs", []):
        source_branch = bp.get("sourceBranch")
        break
    if not source_branch:
        raise click.ClickException("Could not determine source branch from MR.")

    robots = await patronus.list_robots(repo, source_branch=source_branch)
    if not robots:
        click.echo("No Patronus runs found for this merge request.")
        return

    # Use the most recent robot
    robot = robots[0]
    robot_id = robot.get("id")

    if web:
        click.launch(f"https://patronus.labs.jb.gg/robot/{robot_id}")
        return

    if watch:
        from .run import _watch_robot
        await _watch_robot(patronus, robot_id, interval, fail_fast)
        return

    # Show checks for the latest run
    from .run import _print_run_checks
    await _print_run_checks(state, robot_id)


# mr checkout =================================================================


@mr_group.command("checkout")
@click.argument("mr_ref", required=False)
@click.option("-b", "--branch", "local_branch", default=None, help="Local branch name override")
@click.option("-f", "--force", is_flag=True, help="Reset existing local branch")
@pass_state
@async_command
async def mr_checkout(state: CliState, mr_ref: str | None, local_branch: str | None, force: bool):
    """Fetch and check out a merge request's source branch."""
    mr = await resolve_mr(state, mr_ref)

    source_branch = None
    for bp in mr.get("branchPairs", []):
        source_branch = bp.get("sourceBranch")
        break
    if not source_branch:
        raise click.ClickException("Could not determine source branch from MR.")

    branch_name = local_branch or source_branch

    click.echo(f"Fetching and checking out '{branch_name}'...")
    result = subprocess.run(["git", "fetch", "origin", source_branch], capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException(f"git fetch failed: {result.stderr.strip()}")

    checkout_args = ["git", "checkout"]
    if force:
        checkout_args.append("-B")
    else:
        checkout_args.append("-b")
    # -b/-B creates a new local branch tracking the remote
    # If the branch already exists and no --force, try plain checkout
    checkout_args.extend([branch_name, f"origin/{source_branch}"])

    result = subprocess.run(checkout_args, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: branch might already exist, just switch to it
        if not force:
            result = subprocess.run(["git", "checkout", branch_name], capture_output=True, text=True)
        if result.returncode != 0:
            raise click.ClickException(f"git checkout failed: {result.stderr.strip()}")

    click.echo(f"Switched to branch '{branch_name}'.")


# mr diff =====================================================================


@mr_group.command("diff")
@click.argument("mr_ref", required=False)
@click.option("--name-only", is_flag=True, help="Show only file names")
@click.option("--stat", "show_stat", is_flag=True, help="Show diffstat")
@pass_state
@async_command
async def mr_diff(state: CliState, mr_ref: str | None, name_only: bool, show_stat: bool):
    """View changes in a merge request (local git diff between target and source)."""
    mr = await resolve_mr(state, mr_ref)

    source_branch = target_branch = None
    for bp in mr.get("branchPairs", []):
        source_branch = bp.get("sourceBranch")
        target_branch = bp.get("targetBranch")
        break
    if not source_branch or not target_branch:
        raise click.ClickException("Could not determine branches from MR.")

    # Fetch to make sure we have latest refs
    subprocess.run(["git", "fetch", "origin", source_branch, target_branch],
                   capture_output=True, text=True)

    diff_args = ["git", "diff", f"origin/{target_branch}...origin/{source_branch}"]
    if name_only:
        diff_args.append("--name-only")
    elif show_stat:
        diff_args.append("--stat")

    result = subprocess.run(diff_args, text=True)
    raise SystemExit(result.returncode)


# mr create ===================================================================


@mr_group.command("create")
@click.argument("source_branch", required=False)
@click.option("-t", "--title", required=True, help="MR title")
@click.option("-b", "--base", "target_branch", default=None, help="Target branch (default: master)")
@click.option("-d", "--description", default=None, help="MR description")
@click.option("-w", "--web", is_flag=True, help="Open in browser after creation")
@pass_state
@async_command
async def mr_create(state: CliState, source_branch: str | None, title: str,
                    target_branch: str | None, description: str | None, web: bool):
    """Create a new merge request from a branch."""
    project = state.require_project()
    repo = state.require_repo()
    client = state.space_client()

    branch = source_branch or state.context.branch
    if not branch:
        raise click.UsageError(
            "No source branch specified and could not detect current branch. "
            "Pass a branch name as argument."
        )

    target = target_branch or "master"

    result = await client.create_merge_request(
        project=project, repository=repo,
        source_branch=branch, target_branch=target,
        title=title, description=description,
    )

    if state.use_json:
        fmt.print_json(result, state.json_fields)
        return

    number = result.get("number", "?")
    click.secho(f"Created #{number} {title}", bold=True)
    click.echo(f"{branch} -> {target} ({repo})")

    if web:
        url = f"https://jetbrains.team/p/{project}/reviews/{number}/timeline"
        click.launch(url)


# mr close ====================================================================


@mr_group.command("close")
@click.argument("mr_ref", required=False)
@pass_state
@async_command
async def mr_close(state: CliState, mr_ref: str | None):
    """Close a merge request."""
    mr = await resolve_mr(state, mr_ref)
    project = state.require_project()
    client = state.space_client()

    review_id = str(mr.get("number", mr.get("id")))
    await client.set_merge_request_state(project, review_id, "Closed")

    number = mr.get("number", "?")
    title = mr.get("title", "")
    click.echo(f"Closed #{number} {title}")


# mr reopen ===================================================================


@mr_group.command("reopen")
@click.argument("mr_ref", required=False)
@pass_state
@async_command
async def mr_reopen(state: CliState, mr_ref: str | None):
    """Reopen a closed merge request. The source branch must exist."""
    mr = await resolve_mr(state, mr_ref)
    project = state.require_project()
    client = state.space_client()

    review_id = str(mr.get("number", mr.get("id")))
    await client.set_merge_request_state(project, review_id, "Opened")

    number = mr.get("number", "?")
    title = mr.get("title", "")
    click.echo(f"Reopened #{number} {title}")


# mr merge ====================================================================


@mr_group.command("merge")
@click.argument("mr_ref", required=False)
@click.option("--rebase", "strategy", flag_value="REBASE", help="Rebase before merging")
@click.option("--squash", "strategy", flag_value="REBASE_SQUASH_ALL", help="Squash all commits")
@click.option("--autosquash", "strategy", flag_value="REBASE_AUTOSQUASH", help="Rebase with autosquash")
@click.option("--dry-run", "strategy", flag_value="DRY_RUN", help="Dry run instead of merging")
@click.option("-m", "--message", default=None, help="Squash commit message (with --squash)")
@click.option("-w", "--web", is_flag=True, help="Open Patronus page after starting")
@pass_state
@async_command
async def mr_merge(state: CliState, mr_ref: str | None, strategy: str | None, message: str | None, web: bool):
    """Merge a merge request via Patronus safe merge."""
    operation = strategy or "MERGE"

    if operation == "REBASE_SQUASH_ALL" and not message:
        raise click.UsageError("--squash requires -m/--message with a commit message.")

    mr = await resolve_mr(state, mr_ref)
    project = state.require_project()
    space = state.space_client()

    space_operation = _OPERATION_MAP.get(operation, operation)
    result = await space.start_safe_merge(
        project=project,
        review_id=mr["id"],
        operation=space_operation,
        squash_commit_message=message,
    )

    robot_id = result.get("robotId", "?")
    robot_url = result.get("robotUrl", f"https://patronus.labs.jb.gg/robot/{robot_id}")
    status = result.get("status", "?")

    op_label = {"DRY_RUN": "Dry run", "MERGE": "Safe merge", "REBASE": "Rebase merge",
                "REBASE_AUTOSQUASH": "Autosquash merge", "REBASE_SQUASH_ALL": "Squash merge"}
    click.echo(f"{op_label.get(operation, operation)} started: {fmt.styled_status(status)}")
    click.echo(f"Robot ID: {robot_id}")
    click.echo(f"Patronus: {robot_url}")

    if web:
        click.launch(robot_url)
