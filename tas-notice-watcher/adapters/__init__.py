"""Source adapters. One module per source, each behind the same interface."""

from __future__ import annotations

from typing import Iterable

from .base import Adapter, AdapterContext, AdapterError, AdapterParseError, AdapterResult, Limits
from .contracts import ContractsAdapter
from .gazette import GazetteAdapter
from .lobbyists import LobbyistsAdapter
from .tenders import TendersAdapter

ADAPTER_CLASSES = (GazetteAdapter, TendersAdapter, ContractsAdapter, LobbyistsAdapter)


def all_adapters() -> list[Adapter]:
    return [cls() for cls in ADAPTER_CLASSES]


def get_adapters(names: Iterable[str] | None = None) -> list[Adapter]:
    adapters = all_adapters()
    if not names:
        return adapters
    wanted = [name.strip() for name in names if name.strip()]
    by_name = {adapter.name: adapter for adapter in adapters}
    unknown = [name for name in wanted if name not in by_name]
    if unknown:
        raise KeyError(f"unknown source(s): {unknown}; known: {sorted(by_name)}")
    return [by_name[name] for name in wanted]


__all__ = [
    "Adapter",
    "AdapterContext",
    "AdapterError",
    "AdapterParseError",
    "AdapterResult",
    "Limits",
    "ADAPTER_CLASSES",
    "all_adapters",
    "get_adapters",
]
