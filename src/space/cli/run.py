"""space run — Patronus CI run commands."""

import asyncio
import re
import sys
from typing import Any

import click

from .app import CliState, async_command, pass_state, resolve_mr
from . import format as fmt
from ..patronus import PatronusClient

_OPERATION_MAP = {
    "DRY_RUN": "DryRun",
    "MERGE": "Merge",
    "REBASE": "Rebase",
    "REBASE_AUTOSQUASH": "RebaseAutosquash",
    "REBASE_SQUASH_ALL": "RebaseSquashAll",
}


@click.group("run", short_help="Manage Patronus CI runs (dry runs and safe merges)")
def run_group():
    """Manage Patronus CI runs (dry runs and safe merges)."""


# run list ====================================================================


@run_group.command("list")
@click.option("-b", "--branch", default=None, help="Source branch (default: current)")
@click.option("-B", "--base", default=None, help="Target branch filter")
@click.option("-L", "--limit", default=20, type=int, help="Max results (default: 20)")
@click.option("-w", "--web", is_flag=True, help="Open in browser")
@pass_state
@async_command
async def run_list(state: CliState, branch: str | None, base: str | None, limit: int, web: bool):
    """List Patronus runs. Defaults to the current branch."""
    repo = state.require_repo()
    patronus = state.patronus_client()
    source_branch = branch or state.context.branch

    robots = await patronus.list_robots(repo, source_branch=source_branch, target_branch=base)

    if limit and len(robots) > limit:
        robots = robots[:limit]

    if state.use_json:
        fmt.print_json(robots, state.json_fields)
        return

    if not robots:
        click.echo("No Patronus runs found.")
        return

    headers = ["STATUS", "MODE", "BRANCH", "OWNER", "STARTED"]
    rows = []
    for r in robots:
        status = r.get("status", "?")
        mode = r.get("pushMode", "?")
        source = r.get("sourceBranch", "?")
        target = r.get("targetBranch", "?")
        owner = r.get("owner", {}).get("name", "?")
        started = fmt.format_iso(r.get("startDateTime"))
        rows.append([fmt.styled_status(status), mode, f"{source} → {target}", owner, started])

    fmt.print_table(headers, rows, max_widths={2: 60})

    # Print robot IDs for follow-up
    click.echo()
    click.secho("Robot IDs:", bold=True)
    for r in robots:
        click.echo(f"  {r.get('id', '?')}")


# run view ====================================================================


def _parse_robot_id(ref: str) -> str:
    """Extract robot UUID from a robot ID or Patronus URL."""
    # URL: https://patronus.labs.jb.gg/robot/<uuid>
    m = re.search(r"/robot/([0-9a-f-]+)", ref)
    if m:
        return m.group(1)
    return ref


@run_group.command("view")
@click.argument("robot_ref")
@click.option("-w", "--web", is_flag=True, help="Open Patronus page in browser")
@pass_state
@async_command
async def run_view(state: CliState, robot_ref: str, web: bool):
    """View details of a Patronus run: status, TeamCity checks, problems."""
    robot_id = _parse_robot_id(robot_ref)

    if web:
        click.launch(f"https://patronus.labs.jb.gg/robot/{robot_id}")
        return

    await _print_run_details(state, robot_id)


async def _print_run_details(state: CliState, robot_id: str) -> None:
    """Fetch and print full run details."""
    patronus = state.patronus_client()
    robot, tc_checks, problems = await asyncio.gather(
        patronus.get_robot(robot_id),
        patronus.get_robot_teamcity_checks(robot_id),
        patronus.get_robot_problems(robot_id),
    )

    if state.use_json:
        fmt.print_json({"robot": robot, "checks": tc_checks, "problems": problems}, state.json_fields)
        return

    # Header -----
    name = robot.get("name", "?")
    status = robot.get("status", "?")
    click.secho(f"{name}", bold=True)
    click.echo(f"{fmt.styled_status(status)} — {robot.get('pushMode', '?')}")
    click.echo(f"Owner: {robot.get('owner', {}).get('name', '?')}")

    source = robot.get("sourceBranch", "?")
    target = robot.get("targetBranch", "?")
    repo = robot.get("repository", "?")
    click.echo(f"{source} → {target} ({repo})")

    start_dt = robot.get("startDateTime", "")
    if start_dt:
        click.echo(f"Started: {fmt.format_iso(start_dt)}")
    finish_dt = robot.get("finishDateTime")
    if finish_dt:
        click.echo(f"Finished: {fmt.format_iso(finish_dt)}")

    click.echo(f"Patronus: https://patronus.labs.jb.gg/robot/{robot_id}")

    review_url = robot.get("spaceReviewUrl")
    if review_url:
        click.echo(f"Space MR: {review_url}")

    # TC checks -----
    await _print_run_checks(state, robot_id, tc_checks=tc_checks)

    # Problems -----
    problem_list = problems.get("problems", []) if isinstance(problems, dict) else []
    if problem_list:
        click.echo()
        click.secho("Problems", bold=True)
        for p in problem_list:
            click.echo(f"  - {p.get('title', '?')}")
            if p.get("detailsMarkdown"):
                for line in p["detailsMarkdown"].splitlines()[:5]:
                    click.echo(f"    {line}")


async def _print_run_checks(state: CliState, robot_id: str, *, tc_checks: list[dict] | None = None) -> None:
    """Print TeamCity checks for a robot."""
    patronus = state.patronus_client()
    if tc_checks is None:
        tc_checks = await patronus.get_robot_teamcity_checks(robot_id)

    if not tc_checks:
        click.echo()
        click.echo("No TeamCity checks.")
        return

    # Summary -----
    by_status: dict[str, int] = {}
    for check in tc_checks:
        s = check.get("status", "UNKNOWN")
        by_status[s] = by_status.get(s, 0) + 1
    summary_parts = []
    for s in ["SUCCESS", "FAILURE", "RUNNING", "PENDING"]:
        if s in by_status:
            summary_parts.append(f"{by_status[s]} {s.lower()}")
    for s, count in sorted(by_status.items()):
        if s not in ("SUCCESS", "FAILURE", "RUNNING", "PENDING"):
            summary_parts.append(f"{count} {s.lower()}")

    click.echo()
    click.secho(f"TeamCity Checks ({len(tc_checks)} total: {', '.join(summary_parts)})", bold=True)

    headers = ["STATUS", "NAME", "BUILD"]
    rows = []
    for check in tc_checks:
        c_status = check.get("status", "?")
        c_name = check.get("name", "?")
        build_id = str(check.get("buildId", ""))
        rows.append([fmt.styled_status(c_status), c_name, build_id])

    fmt.print_table(headers, rows, max_widths={1: 50})

    # Fetch and display failed check details -----
    failed_checks = [c for c in tc_checks if c.get("status") == "FAILURE"]
    for check in failed_checks:
        attempts = check.get("attempts", [])
        failed_attempts = [a for a in attempts if a.get("status") == "FAILURE"]
        if failed_attempts:
            latest_attempt = failed_attempts[-1]
            attempt_id = latest_attempt.get("id")
            if attempt_id:
                details = await patronus.get_attempt_details(attempt_id)
                failed_tests = details.get("failedTests", [])
                if failed_tests:
                    click.echo()
                    click.secho(f"  Failed tests in {check.get('name', '?')}:", bold=True)
                    for test in failed_tests[:10]:
                        click.echo(f"    - {test.get('name', '?')}")
                    if len(failed_tests) > 10:
                        click.echo(f"    ... and {len(failed_tests) - 10} more")


# run start ===================================================================


@run_group.command("start")
@click.argument("mr_ref", required=False)
@click.option("--merge", "strategy", flag_value="MERGE", help="Start a safe merge")
@click.option("--rebase", "strategy", flag_value="REBASE", help="Rebase merge")
@click.option("--squash", "strategy", flag_value="REBASE_SQUASH_ALL", help="Squash merge")
@click.option("--autosquash", "strategy", flag_value="REBASE_AUTOSQUASH", help="Rebase with autosquash")
@click.option("-m", "--message", default=None, help="Squash commit message")
@click.option("--watch", is_flag=True, help="Watch the run after starting")
@click.option("-w", "--web", is_flag=True, help="Open in browser after starting")
@pass_state
@async_command
async def run_start(state: CliState, mr_ref: str | None, strategy: str | None, message: str | None,
                    watch: bool, web: bool):
    """Start a Patronus dry run or safe merge."""
    operation = strategy or "DRY_RUN"

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

    if watch and robot_id != "?":
        click.echo()
        await _watch_robot(patronus, robot_id, interval=10, fail_fast=False)


# run cancel ==================================================================


@run_group.command("cancel")
@click.argument("robot_ref")
@pass_state
@async_command
async def run_cancel(state: CliState, robot_ref: str):
    """Cancel a running Patronus run."""
    robot_id = _parse_robot_id(robot_ref)
    patronus = state.patronus_client()
    await patronus.cancel_robot(robot_id)
    click.echo(f"Cancelled robot {robot_id}.")


# run watch ===================================================================


@run_group.command("watch")
@click.argument("robot_ref")
@click.option("-i", "--interval", default=10, type=int, help="Refresh interval in seconds (default: 10)")
@click.option("--fail-fast", is_flag=True, help="Exit on first check failure")
@pass_state
@async_command
async def run_watch(state: CliState, robot_ref: str, interval: int, fail_fast: bool):
    """Watch a Patronus run until it completes, showing live check progress."""
    robot_id = _parse_robot_id(robot_ref)
    patronus = state.patronus_client()
    await _watch_robot(patronus, robot_id, interval, fail_fast)


_CHECK_SYMBOLS = {
    "SUCCESS": ("✓", "green"),
    "FAILURE": ("✗", "red"),
    "RUNNING": ("●", "yellow"),
}


async def _watch_robot(patronus: PatronusClient, robot_id: str, interval: int, fail_fast: bool) -> None:
    """Poll a robot until completion, refreshing the terminal display."""
    first_iteration = True

    while True:
        robot, tc_checks = await asyncio.gather(
            patronus.get_robot(robot_id),
            patronus.get_robot_teamcity_checks(robot_id),
        )

        status = robot.get("status", "?")
        name = robot.get("name", "?")

        # Clear previous output (except on first iteration)
        if not first_iteration and fmt.is_tty():
            # Move cursor up and clear lines: header(2) + separator(1) + checks + separator(1) + summary(1)
            lines_to_clear = 5 + len(tc_checks)
            sys.stdout.write(f"\033[{lines_to_clear}A\033[J")
        first_iteration = False

        # Header -----
        click.echo(f"{name} ({robot_id[:12]}...)  [{fmt.styled_status(status)}]")
        click.echo("─" * 60)

        # Checks -----
        for check in tc_checks:
            c_status = check.get("status", "PENDING")
            c_name = check.get("name", "?")
            symbol, color = _CHECK_SYMBOLS.get(c_status, ("○", None))
            if color and fmt.is_tty():
                symbol = click.style(symbol, fg=color)
            click.echo(f"  {symbol} {c_name}")

        # Summary -----
        click.echo("─" * 60)
        by_status: dict[str, int] = {}
        for check in tc_checks:
            s = check.get("status", "PENDING")
            by_status[s] = by_status.get(s, 0) + 1

        parts = []
        if "SUCCESS" in by_status:
            parts.append(f"{by_status['SUCCESS']} passed")
        if "FAILURE" in by_status:
            parts.append(f"{by_status['FAILURE']} failed")
        if "RUNNING" in by_status:
            parts.append(f"{by_status['RUNNING']} running")
        pending = by_status.get("PENDING", 0) + sum(
            v for k, v in by_status.items() if k not in ("SUCCESS", "FAILURE", "RUNNING", "PENDING"))
        if pending:
            parts.append(f"{pending} pending")
        click.echo(" · ".join(parts))

        # Terminal conditions -----
        if status not in ("RUNNING", "PENDING", "STARTING"):
            return

        if fail_fast and by_status.get("FAILURE", 0) > 0:
            raise click.ClickException("Check failed (--fail-fast).")

        await asyncio.sleep(interval)
