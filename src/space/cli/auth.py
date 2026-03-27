"""space auth — Authentication commands."""

import asyncio
import shutil

import click
import httpx

from .app import CliState, async_command, pass_state
from ..client import validate_token
from ..auth import delete_token, resolve_token_source, store_token

# Git credential storage ===============================================================================================


def _confirm_git_login() -> bool:
    """Ask whether to store git credentials. Falls back to click if rich is unavailable."""
    try:
        from rich.prompt import Confirm
        return Confirm.ask("Configure git credentials for git.jetbrains.team?", default=False)
    except ImportError:
        return click.confirm("Configure git credentials for git.jetbrains.team?", default=False)


async def _git_credential_approve(username: str, token: str) -> None:
    """Store git credentials for git.jetbrains.team via git credential approve."""
    git_path = shutil.which("git")
    if git_path is None:
        click.secho("! Git is not installed, skipping credential storage.", fg="yellow")
        return

    credential_input = (
        "protocol=https\n"
        "host=git.jetbrains.team\n"
        f"username={username}\n"
        f"password={token}\n"
        "\n"
    )

    proc = await asyncio.create_subprocess_exec(
        git_path,
        "credential",
        "approve",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=credential_input.encode())

    if proc.returncode == 0:
        click.secho("Git credentials stored for git.jetbrains.team", fg="green")
    else:
        detail = stderr.decode().strip() or stdout.decode().strip()
        click.secho(f"! Git credential storage failed: {detail}", fg="yellow")


# Docker registry login ================================================================================================


def _confirm_docker_login() -> bool:
    """Ask whether to authenticate Docker. Falls back to click if rich is unavailable."""
    try:
        from rich.prompt import Confirm
        return Confirm.ask("Authenticate Docker with registry.jetbrains.team?", default=False)
    except ImportError:
        return click.confirm("Authenticate Docker with registry.jetbrains.team?", default=False)


async def _docker_login(email: str, token: str) -> None:
    """Run docker login with the PAT piped to stdin."""
    docker_path = shutil.which("docker")
    if docker_path is None:
        click.secho("! Docker is not installed, skipping registry login.", fg="yellow")
        return

    proc = await asyncio.create_subprocess_exec(
        docker_path,
        "login",
        "registry.jetbrains.team",
        "--username",
        email,
        "--password-stdin",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=token.encode())

    if proc.returncode == 0:
        click.secho("Docker authenticated with registry.jetbrains.team", fg="green")
    else:
        detail = stderr.decode().strip() or stdout.decode().strip()
        click.secho(f"! Docker login failed: {detail}", fg="yellow")


# Commands =============================================================================================================


@click.group("auth", short_help="Authenticate with JetBrains Space")
def auth_group():
    """Manage authentication state for JetBrains Space."""


_TOKEN_PROMPT = (
    "Personal token: https://jetbrains.team/m/me/authentication?tab=PermanentTokens\n"
    "Application token: Space Admin > Applications > [app] > Authentication > Permanent Tokens\n"
    "Space token"
)


@auth_group.command("login")
@click.option(
    "--token", prompt=_TOKEN_PROMPT, hide_input=True, help="Personal or application token (prompted if omitted)"
)
@click.option(
    "--insecure-storage", is_flag=True, help="Store token in plain text config file instead of system keyring"
)
@async_command
async def auth_login(token: str, insecure_storage: bool):
    """Store credentials for JetBrains Space."""
    # Validate the token against Space API -----------------------------------------------------------------------------
    click.echo("Validating token...")
    try:
        profile = await validate_token(token)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise click.ClickException("Invalid token. Please check that it is correct and not expired.")
        raise click.ClickException(f"Validation failed (HTTP {e.response.status_code}). Try again later.")
    except httpx.ConnectError:
        raise click.ClickException("Could not connect to jetbrains.team. Check your network.")

    # Store the token --------------------------------------------------------------------------------------------------
    def _store() -> None:
        used_keyring, description = store_token(token, insecure=insecure_storage)
        if used_keyring:
            click.secho(f"Token stored in {description}", fg="green")
        else:
            click.secho(f"! Token stored in plain text at {description}", fg="yellow")

    # Application tokens: no git/docker setup --------------------------------------------------------------------------
    if profile.get("kind") == "app":
        click.secho(f"Authenticated as application: {profile['name']}", fg="green")
        _store()
        return

    # User tokens ------------------------------------------------------------------------------------------------------
    username = profile.get("username", "unknown")
    emails = [e["email"] for e in profile.get("emails", []) if "email" in e]
    email = emails[0] if emails else None

    click.secho(f"Authenticated as {username}" + (f" ({email})" if email else ""), fg="green")
    _store()

    # Optional git credential storage ----------------------------------------------------------------------------------
    if email and _confirm_git_login():
        await _git_credential_approve(email, token)

    # Optional Docker registry login -----------------------------------------------------------------------------------
    if email and _confirm_docker_login():
        await _docker_login(email, token)


@auth_group.command("logout")
def auth_logout():
    """Remove stored credentials for JetBrains Space."""
    try:
        delete_token()
        click.echo("Credentials removed.")
    except RuntimeError as e:
        raise click.ClickException(str(e))


_SOURCE_LABELS = {
    "env": "SPACE_TOKEN environment variable",
    "keyring": "system keyring",
    "config": "config file",
}


@auth_group.command("status")
@pass_state
@async_command
async def auth_status(state: CliState):
    """Show authentication status and detected context."""
    source = resolve_token_source()

    if source:
        click.secho("Authenticated", fg="green")
        click.echo(f"  Token source: {_SOURCE_LABELS.get(source, source)}")

        # Show identity via validate_token (works for both user and app tokens)
        try:
            token = state.require_token()
            profile = await validate_token(token)
            if profile.get("kind") == "app":
                click.echo(f"  Application: {profile['name']}")
            else:
                name_obj = profile.get("name") or {}
                full_name = f"{name_obj.get('firstName', '')} {name_obj.get('lastName', '')}".strip()
                username = profile.get("username", "")
                display = full_name or username
                emails = [e["email"] for e in profile.get("emails", []) if "email" in e]
                if display:
                    click.echo(f"  User: {display}" + (f" ({emails[0]})" if emails else ""))
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
            pass

        # Show detected context
        ctx = state.context
        parts = []
        if ctx.project:
            parts.append(f"project={ctx.project}")
        if ctx.repo:
            parts.append(f"repo={ctx.repo}")
        if ctx.branch:
            parts.append(f"branch={ctx.branch}")
        if parts:
            click.echo(f"  Detected context: {', '.join(parts)}")
    else:
        click.secho("Not authenticated", fg="red")
        click.echo("  Set SPACE_TOKEN or run `space auth login`.")
