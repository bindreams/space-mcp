"""space auth — Authentication commands."""

import os

import click

from .app import CliState, async_command, pass_state
from ..context import delete_token, resolve_token, resolve_token_source, store_token


@click.group("auth", short_help="Authenticate with JetBrains Space")
def auth_group():
    """Manage authentication state for JetBrains Space."""


@auth_group.command("login")
@click.option("--token", prompt="Space personal token", hide_input=True,
              help="Personal token (prompted if omitted)")
@click.option("--url", default="https://jetbrains.team", help="Space instance URL")
@click.option("--insecure-storage", is_flag=True,
              help="Store token in plain text config file instead of system keyring")
def auth_login(token: str, url: str, insecure_storage: bool):
    """Store credentials for a Space instance."""
    used_keyring, description = store_token(url, token, insecure=insecure_storage)

    if used_keyring:
        click.secho(f"Token stored in {description}", fg="green")
    else:
        click.secho(f"! Token stored in plain text at {description}", fg="yellow")


@auth_group.command("logout")
@click.option("--url", default="https://jetbrains.team", help="Space instance URL")
def auth_logout(url: str):
    """Remove stored credentials for a Space instance."""
    try:
        delete_token(url)
        click.echo(f"Credentials removed for {url}")
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
        click.secho("✓ Authenticated", fg="green")
        click.echo(f"  Token source: {_SOURCE_LABELS.get(source, source)}")

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
