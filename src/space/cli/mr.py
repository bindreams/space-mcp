"""space mr — Merge request commands."""

from __future__ import annotations

import click

from .app import CliState, async_command, pass_state, resolve_mr
from . import format as fmt
from ..models import (
    Attachment,
    CodeDiscussion,
    MergeRequest,
    MRStateFilter,
    ReviewRole,
    TimelineMessage,
)


@click.group("mr", short_help="Manage merge requests (code reviews)")
def mr_group():
    """Manage JetBrains Space merge requests (code reviews).

    A merge request can be specified by number, URL, branch name,
    or omitted to use the current branch.
    """


# mr view ==============================================================================================================


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


def _open_mr_in_browser(mr: MergeRequest) -> None:
    """Open an MR in the browser."""
    number = mr.number
    url = f"https://jetbrains.team/p/ij/reviews/{number}/timeline"
    click.launch(url)


def _print_mr_details(mr: MergeRequest) -> None:
    """Print MR details in human-readable format."""
    click.secho(f"#{mr.number} {mr.title}", bold=True)
    author_name = mr.created_by.name if mr.created_by else "Unknown"
    click.echo(f"{fmt.styled_status(mr.state.value)} — {author_name}")

    if mr.branch_pair:
        bp = mr.branch_pair
        click.echo(f"{bp.source_branch} → {bp.target_branch} ({bp.repository})")

    if mr.description:
        click.echo()
        click.echo(mr.description)

    # Reviewers --------------------------------------------------------------------------------------------------------
    reviewers = [p for p in mr.participants if p.role != ReviewRole.AUTHOR]
    if reviewers:
        click.echo()
        click.secho("Reviewers", bold=True)
        for p in reviewers:
            symbol = fmt.reviewer_symbol(p.state.value)
            click.echo(f"  {symbol} {p.user.name} ({p.state.value})")


# mr list ==============================================================================================================


@mr_group.command("list")
@click.option(
    "-s",
    "--state",
    "state_filter",
    type=click.Choice(["opened", "closed", "merged", "all"], case_sensitive=False),
    default="opened",
    help="Filter by state (default: opened)"
)
@click.option("-H", "--head", "head_branch", default=None, help="Filter by source branch")
@click.option("-A", "--author", default=None, help="Filter by author username")
@click.option("-L", "--limit", default=20, type=int, help="Max results (default: 20)")
@click.option("-w", "--web", is_flag=True, help="Open in browser")
@pass_state
@async_command
async def mr_list(
    state: CliState, state_filter: str, head_branch: str | None, author: str | None, limit: int, web: bool
):
    """List merge requests. Shows open MRs by default."""
    project = state.require_project()
    repo = state.require_repo()
    client = state.space_client()

    api_state: MRStateFilter | None = None
    if state_filter and state_filter != "all":
        api_state = MRStateFilter(state_filter.capitalize())

    reviews: list[MergeRequest] = []
    try:
        async for mr in client.list_merge_requests(
            project=project,
            repository=repo,
            branch=head_branch,
            state=api_state,
            author=author,
        ):
            reviews.append(mr)
            if len(reviews) >= limit:
                break
    except ValueError as e:
        # e.g. author handle did not resolve to a Space user
        raise click.ClickException(str(e))

    if state.use_json:
        fmt.print_json(reviews, state.json_fields)
        return

    if not reviews:
        click.echo("No merge requests found.")
        return

    headers = ["#", "TITLE", "STATE", "AUTHOR", "BRANCH"]
    rows = []
    for mr in reviews:
        mr_author = mr.created_by.name if mr.created_by else "Unknown"
        branch = ""
        if mr.branch_pair:
            branch = f"{mr.branch_pair.source_branch} → {mr.branch_pair.target_branch}"
        number = str(mr.number or mr.id)
        rows.append([number, mr.title, fmt.styled_status(mr.state.value), mr_author, branch])

    fmt.print_table(headers, rows, max_widths={1: 50, 4: 60})


# mr timeline ==========================================================================================================


def _print_attachments(attachments: tuple[Attachment, ...], indent: str = "  ") -> None:
    """Print attachment lines if present."""
    for att in attachments:
        size_str = f" ({fmt.human_size(att.size_bytes)})" if att.size_bytes else ""
        click.echo(f"{indent}📎 {att.name}{size_str} [id: {att.id}]")


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

    review_id = str(mr.number or mr.id)
    items = await client.get_merge_request_discussions(project, repo, review_id)

    if state.use_json:
        fmt.print_json(items, state.json_fields)
        return

    if not items:
        click.echo("No timeline items.")
        return

    current_day = ""
    for item in items:
        if isinstance(item, CodeDiscussion):
            first_ts = item.comments[0].created_at if item.comments else None
            day = fmt.format_datetime_date(first_ts)
            if day and day != current_day:
                current_day = day
                click.echo()
                click.secho(day, bold=True)

            file_path = item.file or "?"
            line_num = item.line if item.line is not None else "?"
            resolved = " [resolved]" if item.resolved else ""
            if item.comments:
                first = item.comments[0]
                author_name = first.author.name
                time_str = fmt.format_datetime(first.created_at)
                click.echo(f"  {author_name} ({time_str}) on {file_path}:{line_num}{resolved}")
                click.echo(f"    {first.text}")
                _print_attachments(first.attachments, indent="    ")
                for reply in item.comments[1:]:
                    reply_author = reply.author.name
                    if reply.text.startswith("User resolved the discussion"):
                        click.echo(f"    └ {reply_author}: resolved the discussion")
                    elif reply.text.startswith("User reopened the discussion"):
                        click.echo(f"    └ {reply_author}: reopened the discussion")
                    else:
                        click.echo(f"    └ {reply_author}: {reply.text}")
                    _print_attachments(reply.attachments, indent="      ")

        elif isinstance(item, TimelineMessage):
            day = fmt.format_datetime_date(item.created_at)
            if day and day != current_day:
                current_day = day
                click.echo()
                click.secho(day, bold=True)

            author_name = item.author.name
            time_str = fmt.format_datetime(item.created_at)
            click.echo(f"  {author_name} ({time_str}): {item.text}")
            _print_attachments(item.attachments, indent="    ")

            for reply in item.thread_replies:
                reply_author = reply.author.name
                click.echo(f"    └ {reply_author}: {reply.text}")
                _print_attachments(reply.attachments, indent="      ")


# mr checks ============================================================================================================


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
    project = state.require_project()
    patronus = state.patronus_client()

    if not mr.branch_pair:
        raise click.ClickException("Could not determine source branch from MR.")
    source_branch = mr.branch_pair.source_branch
    target_branch = mr.branch_pair.target_branch

    review_number = mr.number or mr.id
    runs = await patronus.list_runs_for_review(
        project,
        review_number,
        source_branch=source_branch,
        target_branch=target_branch,
    )
    if not runs:
        click.echo("No Patronus runs found for this merge request.")
        return

    run = runs[0]

    if web:
        click.launch(f"https://patronus.labs.jb.gg/robot/{run.id}")
        return

    if watch:
        from .run import _watch_run
        await _watch_run(patronus, run.id, interval, fail_fast=fail_fast)
        return

    from .run import _print_run_checks
    await _print_run_checks(state, run.id)


# Register action commands (checkout, diff, create, close, reopen, merge, download)
from . import mr_actions as _mr_actions  # noqa: E402, F401
