"""space status — Quick dashboard command."""

import click

from .app import CliState, async_command, pass_state
from . import format as fmt


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

    # Find MR for current branch -----
    space = state.space_client()
    mr = await space.find_merge_request_by_branch(project, repo, branch)

    if mr:
        number = mr.get("number", "?")
        title = mr.get("title", "?")
        mr_state = mr.get("state", "?")
        click.echo()
        click.echo(f"Merge Request #{number}: {title} [{fmt.styled_status(mr_state)}]")

        participants = mr.get("participants", [])
        reviewers = [p for p in participants if p.get("role") != "Author"]
        if reviewers:
            reviewer_parts = []
            for p in reviewers:
                user = p.get("user", {})
                name = fmt.extract_name(user)
                symbol = fmt.reviewer_symbol(p.get("state"))
                reviewer_parts.append(f"{name} {symbol}")
            click.echo(f"  Reviewers: {', '.join(reviewer_parts)}")

        if state.use_json:
            data["mr"] = mr
    else:
        click.echo()
        click.echo("No merge request found for this branch.")
        if state.use_json:
            data["mr"] = None

    # Find latest Patronus run -----
    patronus = state.patronus_client()
    try:
        robots = await patronus.list_robots(repo, source_branch=branch)
    except Exception:
        robots = []

    if robots:
        latest = robots[0]
        robot_status = latest.get("status", "?")
        mode = latest.get("pushMode", "?")
        started = fmt.format_iso(latest.get("startDateTime"))
        finished = fmt.format_iso(latest.get("finishDateTime"))

        click.echo()
        robot_id = latest.get("id", "?")
        time_info = f"Started: {started}"
        if finished:
            time_info += f" → Finished: {finished}"
        click.echo(f"Latest Run: {robot_id[:12]}... [{fmt.styled_status(robot_status)}] ({mode})")
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
