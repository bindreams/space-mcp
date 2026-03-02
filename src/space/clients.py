import os

from .client import SpaceClient
from .patronus import PatronusClient

# Lazy-initialize clients (allows server to start even without token for tools/list)
_client: SpaceClient | None = None
_patronus_client: PatronusClient | None = None


def get_client() -> SpaceClient:
    """Get or create the Space client."""
    global _client
    if _client is None:
        token = os.environ.get("SPACE_TOKEN")
        if not token:
            raise ValueError("SPACE_TOKEN environment variable is required")
        _client = SpaceClient(token)
    return _client


def get_patronus_client() -> PatronusClient:
    """Get or create the Patronus client. Reuses SPACE_TOKEN for auth."""
    global _patronus_client
    if _patronus_client is None:
        token = os.environ.get("SPACE_TOKEN")
        if not token:
            raise ValueError("SPACE_TOKEN environment variable is required")
        _patronus_client = PatronusClient(token)
    return _patronus_client
