from app.adapters.asura import AsuraScansAdapter
from app.adapters.thunderscans import ThunderScansAdapter
from app.adapters.naver import NaverWebtoonAdapter
from app.adapters.generic_manga import GenericMangaAdapter
from app.adapters.manga import MangaSourceAdapter


class MangaAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[MangaSourceAdapter] = [
            AsuraScansAdapter(),
            ThunderScansAdapter(),
            NaverWebtoonAdapter(),
            GenericMangaAdapter(),
        ]

    def register(
        self,
        adapter: MangaSourceAdapter,
        *,
        first: bool = True,
    ) -> None:
        if first:
            self._adapters.insert(0, adapter)
        else:
            self._adapters.append(adapter)

    def resolve(self, url: str) -> MangaSourceAdapter:
        for adapter in self._adapters:
            if adapter.matches(url):
                return adapter
        raise RuntimeError("No manga adapter matched URL.")

    def names(self) -> list[str]:
        return [adapter.name for adapter in self._adapters]


manga_registry = MangaAdapterRegistry()
