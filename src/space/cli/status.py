"""space status — Quick dashboard command."""

from __future__ import annotations

import click
import httpx

from .app import CliState, async_command, pass_state
from . import format as fmt
from ..auth import AuthenticationError
from ..models.status import ACTIVE_STATUSES, effective_status
from ..patronus import fetch_checks_for_active


@click.command("status", short_help="Show status of your merge requests and CI runs")
@pass_state
@async_command
async def status_command(state: CliState):
    """Show a summary of your current branch's MR and CI status."""
    project = state.require_project()
    repo = state.require_repo()
    branch = state.context.branch

    if not branch:
        raise click.UsageError("Could not detect current branch.")

    if state.use_json:
        data: dict = {"branch": branch, "project": project, "repo": repo}

    click.secho(f"Current branch: {branch} ({repo})", bold=True)

    # Find MR for current branch ---------------------------------------------------------------------------------------
    space = state.space_client()
    mr = await space.find_merge_request_by_branch(project, repo, branch)

    if mr:
        click.echo()
        click.echo(f"Merge Request #{mr.number}: {mr.title} [{fmt.styled_status(mr.state.value)}]")

        from ..models import ReviewRole
        reviewers = [p for p in mr.participants if p.role != ReviewRole.AUTHOR]
        if reviewers:
            reviewer_parts = []
            for p in reviewers:
                symbol = fmt.reviewer_symbol(p.state.value)
                reviewer_parts.append(f"{p.user.name} {symbol}")
            click.echo(f"  Reviewers: {', '.join(reviewer_parts)}")

        if state.use_json:
            data["mr"] = mr
    else:
        click.echo()
        click.echo("No merge request found for this branch.")
        if state.use_json:
            data["mr"] = None

    # Find latest Patronus run -----------------------------------------------------------------------------------------
    patronus = state.patronus_client()
    try:
        if mr:
            review_number = mr.number or mr.id
            target = mr.branch_pair.target_branch if mr.branch_pair else None
            runs = await patronus.list_runs_for_review(
                project,
                review_number,
                source_branch=branch,
                target_branch=target,
            )
        else:
            runs = await patronus.list_runs(source_branch=branch)
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, AuthenticationError):
        runs = []

    if runs:
        latest = runs[0]

        # Derive effective status for active runs ----------------------------------------------------------------------
        checks_by_run = await fetch_checks_for_active(patronus, [latest])
        display_status = effective_status(latest, checks_by_run.get(latest.id))

        click.echo()
        click.echo(f"Latest Run: {latest.id[:12]}... [{fmt.styled_status(display_status)}] ({latest.push_mode.value})")
        if latest.started_at:
            time_info = f"Started: {fmt.format_datetime(latest.started_at)}"
            if latest.finished_at:
                time_info += f" → Finished: {fmt.format_datetime(latest.finished_at)}"
            click.echo(f"  {time_info}")

        if state.use_json:
            data["latest_run"] = latest
    else:
        click.echo()
        click.echo("No Patronus runs found.")
        if state.use_json:
            data["latest_run"] = None

    if state.use_json:
        fmt.print_json(data, state.json_fields)
