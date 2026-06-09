"""space api — Raw API access command."""

import json
import sys

import click
import httpx

from .app import CliState, async_command, pass_state
from ..transport import DEFAULT_REQUEST_TIMEOUT


@click.command("api", short_help="Make an authenticated API request")
@click.argument("endpoint")
@click.option("--patronus", "use_patronus", is_flag=True, help="Target Patronus API (default: Space)")
@click.option("-X", "--method", default="GET", help="HTTP method (default: GET)")
@click.option("-f", "--field", multiple=True, help="Add JSON body field as key=value (repeatable)")
@click.option("-H", "--header", "extra_headers", multiple=True, help="Add header as key:value (repeatable)")
@click.option("--input", "input_file", default=None, help="Read body from file (- for stdin)")
@click.option("-i", "--include", "include_headers", is_flag=True, help="Include response headers")
@pass_state
@async_command
async def api_command(
    state: CliState, endpoint: str, use_patronus: bool, method: str, field: tuple, extra_headers: tuple,
    input_file: str | None, include_headers: bool
):
    """Make an authenticated request to Space or Patronus REST API."""
    token = state.require_token()

    if use_patronus:
        base_url = "https://patronus.labs.jb.gg"
    else:
        base_url = "https://jetbrains.team"

    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    # Extra headers
    for h in extra_headers:
        if ":" in h:
            key, value = h.split(":", 1)
            headers[key.strip()] = value.strip()

    # Body
    body = None
    if field:
        body = {}
        for f in field:
            if "=" in f:
                key, value = f.split("=", 1)
                body[key] = value
        headers["Content-Type"] = "application/json"

    if input_file:
        if input_file == "-":
            body = json.loads(sys.stdin.read())
        else:
            with open(input_file) as fh:
                body = json.loads(fh.read())
        headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT) as client:
        response = await client.request(method, url, headers=headers, json=body)

        if include_headers:
            click.echo(f"HTTP/{response.http_version} {response.status_code}")
            for key, value in response.headers.items():
                click.echo(f"{key}: {value}")
            click.echo()

        # Try to pretty-print JSON, fall back to raw text
        try:
            data = response.json()
            click.echo(json.dumps(data, indent=2, default=str))
        except (json.JSONDecodeError, ValueError):
            click.echo(response.text)

        if response.status_code >= 400:
            raise SystemExit(1)
