"""Space CLI entry point."""

import click

from .cli.app import CliState
from .cli.mr import mr_group
from .cli.run import run_group
from .cli.auth import auth_group
from .cli.api import api_command
from .cli.status import status_command


class JsonParamType(click.ParamType):
    """Custom parameter type for --json that accepts optional field list.

    --json         → empty string (all fields)
    --json fields  → comma-separated field names
    (not passed)   → None
    """
    name = "fields"

    def convert(self, value, param, ctx):
        if value is None:
            return None
        return value


@click.group(invoke_without_command=True)
@click.option("-P", "--project", default=None, help="Override project key")
@click.option("-R", "--repo", default=None, help="Override repository name")
@click.option(
    "--json",
    "json_fields",
    default=None,
    required=False,
    is_eager=True,
    help="Output JSON (optionally: comma-separated field list)"
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.version_option(package_name="space")
@click.pass_context
def main(ctx, project, repo, json_fields, no_color):
    """space — JetBrains Space CLI"""
    if no_color:
        ctx.color = False

    ctx.ensure_object(dict)
    ctx.obj = CliState(project=project, repo=repo, json_fields=json_fields)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# Register command groups ----------------------------------------------------------------------------------------------
main.add_command(mr_group)
main.add_command(run_group)
main.add_command(auth_group)
main.add_command(api_command)
main.add_command(status_command)

if __name__ == "__main__":
    main()
