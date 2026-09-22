from typing import Any

import httpx

from app.core.config import Settings


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positioned = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(positioned))


class OpenAlexProvider:
    def __init__(self, settings: Settings) -> None:
        headers = {"User-Agent": f"NotebookAgent/0.1 ({settings.openalex_mailto})"}
        self.client = httpx.AsyncClient(
            base_url="https://api.openalex.org", headers=headers, timeout=30
        )
        self.mailto = settings.openalex_mailto

    @staticmethod
    def normalize(work: dict[str, Any]) -> dict[str, Any]:
        primary = work.get("primary_location") or {}
        source = primary.get("source") or {}
        return {
            "paper_id": work.get("id", "").rsplit("/", 1)[-1],
            "title": work.get("display_name") or "",
            "authors": [
                author.get("author", {}).get("display_name", "")
                for author in work.get("authorships", [])
            ],
            "year": work.get("publication_year"),
            "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
            "doi": work.get("doi"),
            "url": primary.get("landing_page_url") or work.get("doi"),
            "citation_count": work.get("cited_by_count", 0),
            "source": source.get("display_name") or "OpenAlex",
        }

    async def search(
        self,
        query: str,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        params: dict[str, Any] = {"search": query, "per-page": min(limit, 50)}
        if filters:
            params["filter"] = ",".join(filters)
        if self.mailto:
            params["mailto"] = self.mailto
        response = await self.client.get("/works", params=params)
        response.raise_for_status()
        return [self.normalize(work) for work in response.json().get("results", [])]

    async def get(self, paper_id: str) -> dict[str, Any]:
        response = await self.client.get(f"/works/{paper_id}")
        response.raise_for_status()
        return self.normalize(response.json())

    async def close(self) -> None:
        await self.client.aclose()
