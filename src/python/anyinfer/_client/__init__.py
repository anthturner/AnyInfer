"""Client orchestration: the async core, the sync facade, and the tool loop."""

from .async_client import AsyncClient, AsyncStream, MessagesInput
from .models import CatalogEntryFit, CatalogView
from .providers import ProviderSettings
from .rankers import semantic_ranker
from .sync_client import Client, SyncStream
from .tools import Tool, tool

__all__ = [
    "AsyncClient",
    "AsyncStream",
    "CatalogEntryFit",
    "CatalogView",
    "Client",
    "MessagesInput",
    "ProviderSettings",
    "SyncStream",
    "Tool",
    "semantic_ranker",
    "tool",
]
