"""space mr — Merge request action commands (checkout, diff, create, close, reopen, merge, download, comment, discuss, reply)."""

from __future__ import annotations

import subprocess

import click

from .app import CliState, async_command, pass_state, resolve_mr
from . import format as fmt
from .mr import mr_group

_OPERATION_MAP = {
    "DRY_RUN": "DryRun",
    "MERGE": "Merge",
    "REBASE": "Rebase",
    "REBASE_AUTOSQUASH": "RebaseAutosquash",
    "REBASE_SQUASH_ALL": "RebaseSquashAll",
}


# mr checkout =====


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
    if mr.branch_pair:
        source_branch = mr.branch_pair.source_branch
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
    checkout_args.extend([branch_name, f"origin/{source_branch}"])

    result = subprocess.run(checkout_args, capture_output=True, text=True)
    if result.returncode != 0:
        if not force:
            result = subprocess.run(["git", "checkout", branch_name], capture_output=True, text=True)
        if result.returncode != 0:
            raise click.ClickException(f"git checkout failed: {result.stderr.strip()}")

    click.echo(f"Switched to branch '{branch_name}'.")


# mr diff =====


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
    if mr.branch_pair:
        source_branch = mr.branch_pair.source_branch
        target_branch = mr.branch_pair.target_branch
    if not source_branch or not target_branch:
        raise click.ClickException("Could not determine branches from MR.")

    subprocess.run(["git", "fetch", "origin", source_branch, target_branch],
                   capture_output=True, text=True)

    diff_args = ["git", "diff", f"origin/{target_branch}...origin/{source_branch}"]
    if name_only:
        diff_args.append("--name-only")
    elif show_stat:
        diff_args.append("--stat")

    result = subprocess.run(diff_args, text=True)
    raise SystemExit(result.returncode)


# mr create =====


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

    click.secho(f"Created #{result.number} {title}", bold=True)
    click.echo(f"{branch} -> {target} ({repo})")

    if web:
        url = f"https://jetbrains.team/p/{project}/reviews/{result.number}/timeline"
        click.launch(url)


# mr close =====


@mr_group.command("close")
@click.argument("mr_ref", required=False)
@pass_state
@async_command
async def mr_close(state: CliState, mr_ref: str | None):
    """Close a merge request."""
    mr = await resolve_mr(state, mr_ref)
    project = state.require_project()
    client = state.space_client()

    review_id = str(mr.number or mr.id)
    await client.set_merge_request_state(project, review_id, "Closed")

    click.echo(f"Closed #{mr.number} {mr.title}")


# mr reopen =====


@mr_group.command("reopen")
@click.argument("mr_ref", required=False)
@pass_state
@async_command
async def mr_reopen(state: CliState, mr_ref: str | None):
    """Reopen a closed merge request. The source branch must exist."""
    mr = await resolve_mr(state, mr_ref)
    project = state.require_project()
    client = state.space_client()

    review_id = str(mr.number or mr.id)
    await client.set_merge_request_state(project, review_id, "Opened")

    click.echo(f"Reopened #{mr.number} {mr.title}")


# mr merge =====


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
        review_id=mr.id,
        operation=space_operation,
        squash_commit_message=message,
    )

    if isinstance(result, list):
        from .run import _handle_safe_merge_events
        _handle_safe_merge_events(result)
        return

    run_id = result.get("robotId", "?")
    run_url = result.get("robotUrl", f"https://patronus.labs.jb.gg/robot/{run_id}")
    status = result.get("status", "?")

    op_label = {"DRY_RUN": "Dry run", "MERGE": "Safe merge", "REBASE": "Rebase merge",
                "REBASE_AUTOSQUASH": "Autosquash merge", "REBASE_SQUASH_ALL": "Squash merge"}
    click.echo(f"{op_label.get(operation, operation)} started: {fmt.styled_status(status)}")
    click.echo(f"Run ID: {run_id}")
    click.echo(f"Patronus: {run_url}")

    if web:
        click.launch(run_url)


# mr download =====


@mr_group.command("download")
@click.argument("attachment_id")
@click.option("-o", "--output", "output_path", default=None,
              help="Output file path (required for binary files)")
@pass_state
@async_command
async def mr_download(state: CliState, attachment_id: str, output_path: str | None):
    """Download an attachment from an MR discussion by its ID."""
    client = state.space_client()
    content, content_type = await client.download_attachment(attachment_id)

    if output_path is None:
        if content_type and content_type.startswith("text/"):
            click.echo(content.decode("utf-8", errors="replace"))
        else:
            raise click.UsageError(
                "Binary file — use -o/--output to specify a file path."
            )
    else:
        with open(output_path, "wb") as f:
            f.write(content)
        size = fmt.human_size(len(content))
        click.echo(f"Downloaded {size} to {output_path}")


# mr delete =====


@mr_group.command("delete")
@click.argument("mr_refs", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
@pass_state
@async_command
async def mr_delete(state: CliState, mr_refs: tuple[str, ...], yes: bool):
    """Delete one or more merge requests."""
    project = state.require_project()
    client = state.space_client()

    if not yes:
        click.echo(f"About to delete {len(mr_refs)} merge request(s): {', '.join(mr_refs)}")
        if not click.confirm("Proceed?"):
            raise SystemExit(0)

    ok, errors = 0, []
    for ref in mr_refs:
        try:
            await client.set_merge_request_state(project, ref, "Deleted")
            ok += 1
        except Exception as exc:
            errors.append((ref, str(exc)))

    click.secho(f"Deleted {ok} merge request(s).", fg="green")
    for ref, err in errors:
        click.secho(f"  Failed to delete {ref}: {err}", fg="red")


# mr comment =====


@mr_group.command("comment")
@click.argument("mr_ref", required=True)
@click.argument("text", required=True)
@pass_state
@async_command
async def mr_comment(state: CliState, mr_ref: str, text: str):
    """Post a general comment on a merge request."""
    mr = await resolve_mr(state, mr_ref)
    client = state.space_client()
    await client.post_comment(state.require_project(), str(mr.number), text)
    click.secho(f"Comment posted on MR {mr.number}.", fg="green")


# mr discuss =====


@mr_group.command("discuss")
@click.argument("mr_ref", required=True)
@click.argument("text", required=True)
@click.option("--file", "filename", required=True, help="File path for the inline comment")
@click.option("--line", "line", required=True, type=int, help="Line number (new side)")
@click.option("--revision", "revision", required=True, help="Git commit SHA")
@pass_state
@async_command
async def mr_discuss(state: CliState, mr_ref: str, text: str, filename: str, line: int, revision: str):
    """Create an inline code discussion on a merge request."""
    mr = await resolve_mr(state, mr_ref)
    client = state.space_client()
    channel_id = await client.create_code_discussion(
        state.require_project(), str(mr.number),
        state.require_repo(), revision, filename, line, text,
    )
    click.secho(f"Code discussion created on {filename}:{line}.", fg="green")
    click.echo(f"  Discussion channel: {channel_id}")


# mr reply =====


@mr_group.command("reply")
@click.argument("mr_ref", required=True)
@click.argument("text", required=True)
@click.option("--discussion", "channel_id", required=True, help="Discussion channel ID (from timeline output)")
@pass_state
@async_command
async def mr_reply(state: CliState, mr_ref: str, text: str, channel_id: str):
    """Reply to a code discussion on a merge request."""
    await resolve_mr(state, mr_ref)  # validate MR exists
    client = state.space_client()
    await client.reply_to_discussion(channel_id, text)
    click.secho("Reply posted.", fg="green")
