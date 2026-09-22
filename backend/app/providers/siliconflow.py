from typing import Any

import httpx

from app.core.config import Settings


class SiliconFlowProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.siliconflow_base_url,
            headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
            timeout=90,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.settings.siliconflow_api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is not configured")
        response = await self.client.post(
            "/embeddings", json={"model": self.settings.embedding_model, "input": texts}
        )
        response.raise_for_status()
        vectors = [item["embedding"] for item in response.json()["data"]]
        for vector in vectors:
            if len(vector) != self.settings.embedding_dim:
                raise ValueError(
                    f"embedding dimension {len(vector)} != configured {self.settings.embedding_dim}"
                )
        return vectors

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[dict[str, Any]]:
        if not documents:
            return []
        if not self.settings.siliconflow_api_key:
            return [
                {"index": index, "relevance_score": 1.0 / (index + 1), "document": document}
                for index, document in enumerate(documents[:top_n])
            ]
        response = await self.client.post(
            "/rerank",
            json={
                "model": self.settings.rerank_model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
                "return_documents": False,
            },
        )
        response.raise_for_status()
        return list(response.json()["results"])

    async def close(self) -> None:
        await self.client.aclose()
