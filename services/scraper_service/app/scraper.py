import httpx

from app.adapters.registry import registry
from app.fetcher import fetch_html


async def scrape_url(
    client: httpx.AsyncClient,
    *,
    url: str,
    mode: str,
) -> tuple[str, str, object, bytes]:
    fetched = await fetch_html(
        client,
        url=url,
    )

    adapter = registry.resolve(fetched.final_url)
    result = adapter.extract(
        fetched.final_url,
        fetched.content.decode(
            "utf-8",
            errors="replace",
        ),
        mode,
    )

    return (
        fetched.final_url,
        adapter.name,
        result,
        fetched.content,
    )
