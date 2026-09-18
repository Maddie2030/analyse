from app.adapters.base import SourceAdapter
from app.adapters.generic import GenericAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        # Put specific domain adapters before GenericAdapter.
        self._adapters: list[SourceAdapter] = [
            GenericAdapter(),
        ]

    def resolve(self, url: str) -> SourceAdapter:
        for adapter in self._adapters:
            if adapter.matches(url):
                return adapter
        raise RuntimeError("No scraper adapter matched URL.")


registry = AdapterRegistry()
