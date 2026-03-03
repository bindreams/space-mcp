"""space auth — Authentication commands."""

import json
import os

import click

from .app import CliState, async_command, pass_state
from ..context import _CREDENTIALS_FILE, load_stored_token, resolve_token

_CREDENTIALS_DIR = _CREDENTIALS_FILE.parent


@click.group("auth", short_help="Authenticate with JetBrains Space")
def auth_group():
    """Manage authentication state for JetBrains Space."""


@auth_group.command("login")
@click.option("--token", prompt="Space personal token", hide_input=True,
              help="Personal token (prompted if omitted)")
@click.option("--url", default="https://jetbrains.team", help="Space instance URL")
def auth_login(token: str, url: str):
    """Store credentials for a Space instance."""
    _CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    # Read existing credentials
    creds = {}
    if _CREDENTIALS_FILE.exists():
        creds = json.loads(_CREDENTIALS_FILE.read_text())

    creds[url] = {"token": token}
    _CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    _CREDENTIALS_FILE.chmod(0o600)

    click.echo(f"Credentials stored for {url}")
    click.echo(f"  File: {_CREDENTIALS_FILE}")


@auth_group.command("logout")
@click.option("--url", default="https://jetbrains.team", help="Space instance URL")
def auth_logout(url: str):
    """Remove stored credentials for a Space instance."""
    if not _CREDENTIALS_FILE.exists():
        click.echo("No stored credentials found.")
        return

    creds = json.loads(_CREDENTIALS_FILE.read_text())
    if url in creds:
        del creds[url]
        _CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
        click.echo(f"Credentials removed for {url}")
    else:
        click.echo(f"No credentials stored for {url}")


@auth_group.command("status")
@pass_state
@async_command
async def auth_status(state: CliState):
    """Show authentication status and detected context."""
    token = resolve_token()

    if token:
        # Determine source
        if os.environ.get("SPACE_TOKEN"):
            source = "SPACE_TOKEN environment variable"
        elif _CREDENTIALS_FILE.exists():
            source = str(_CREDENTIALS_FILE)
        else:
            source = "unknown"

        click.secho("✓ Authenticated", fg="green")
        click.echo(f"  Token source: {source}")

        # Try to get user identity
        try:
            patronus = state.patronus_client()
            repo = state.context.repo
            if repo:
                me = await patronus.get_me(repo)
                name = me.get("name", "")
                email = me.get("email", "")
                if name:
                    click.echo(f"  User: {name}" + (f" ({email})" if email else ""))
        except Exception:
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
        click.secho("✗ Not authenticated", fg="red")
        click.echo("  Set SPACE_TOKEN or run `space auth login`.")


# load_stored_token is re-exported from context.py for backwards compatibility
