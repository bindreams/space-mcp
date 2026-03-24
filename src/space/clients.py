from .client import SpaceClient
from .context import AuthenticationError, resolve_token
from .patronus import PatronusClient

# Lazy-initialize clients (allows server to start even without token for tools/list)
_client: SpaceClient | None = None
_patronus_client: PatronusClient | None = None


def get_client() -> SpaceClient:
    """Get or create the Space client.

    Raises:
        AuthenticationError: If no token is available from env or stored credentials.
    """
    global _client
    if _client is None:
        token = resolve_token()
        if not token:
            raise AuthenticationError(
                "Authentication required. Set the SPACE_TOKEN environment variable "
                "or run `space auth login` to store credentials."
            )
        _client = SpaceClient(token)
    return _client


def get_patronus_client() -> PatronusClient:
    """Get or create the Patronus client.

    Raises:
        AuthenticationError: If no token is available from env or stored credentials.
    """
    global _patronus_client
    if _patronus_client is None:
        token = resolve_token()
        if not token:
            raise AuthenticationError(
                "Authentication required. Set the SPACE_TOKEN environment variable "
                "or run `space auth login` to store credentials."
            )
        _patronus_client = PatronusClient(token, space_client=get_client())
    return _patronus_client
