from typing import Any

from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient, RRFRanker

from app.core.config import Settings
from app.retrieval.types import SearchHit


class MilvusStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = MilvusClient(uri=settings.milvus_uri)

    def _content_field(self, schema: Any, name: str = "content") -> None:
        schema.add_field(
            name,
            DataType.VARCHAR,
            max_length=65_535,
            enable_analyzer=True,
            multi_analyzer_params={
                "analyzers": {
                    "english": {"type": "english"},
                    "chinese": {"type": "chinese"},
                    "default": {"tokenizer": "icu", "filter": ["removepunct"]},
                },
                "by_field": "language",
                "alias": {"en": "english", "zh": "chinese"},
            },
        )

    def ensure_collection(self) -> None:
        name = self.settings.milvus_collection
        if self.client.has_collection(name):
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("notebook_id", DataType.VARCHAR, max_length=64)
        schema.add_field("document_id", DataType.VARCHAR, max_length=64)
        schema.add_field("document_version_id", DataType.VARCHAR, max_length=64)
        schema.add_field("section_id", DataType.VARCHAR, max_length=64)
        schema.add_field("ordinal", DataType.INT64)
        schema.add_field("title", DataType.VARCHAR, max_length=1024)
        schema.add_field("language", DataType.VARCHAR, max_length=24)
        schema.add_field("page_start", DataType.INT64)
        schema.add_field("page_end", DataType.INT64)
        self._content_field(schema)
        schema.add_field("dense", DataType.FLOAT_VECTOR, dim=self.settings.embedding_dim)
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("is_active", DataType.BOOL)
        schema.add_function(
            Function(
                name="content_bm25",
                input_field_names=["content"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )
        indexes = self.client.prepare_index_params()
        indexes.add_index("dense", index_type="AUTOINDEX", metric_type="COSINE")
        indexes.add_index("sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        self.client.create_collection(name, schema=schema, index_params=indexes)

    def ensure_document_collection(self) -> None:
        name = self.settings.milvus_document_collection
        if self.client.has_collection(name):
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("profile_id", DataType.VARCHAR, is_primary=True, max_length=80)
        schema.add_field("notebook_id", DataType.VARCHAR, max_length=64)
        schema.add_field("document_id", DataType.VARCHAR, max_length=64)
        schema.add_field("document_version_id", DataType.VARCHAR, max_length=64)
        schema.add_field("title", DataType.VARCHAR, max_length=1024)
        schema.add_field("language", DataType.VARCHAR, max_length=24)
        schema.add_field("is_active", DataType.BOOL)
        self._content_field(schema, "text")
        schema.add_field("dense", DataType.FLOAT_VECTOR, dim=self.settings.embedding_dim)
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="text_bm25",
                input_field_names=["text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )
        indexes = self.client.prepare_index_params()
        indexes.add_index("dense", index_type="AUTOINDEX", metric_type="COSINE")
        indexes.add_index("sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        self.client.create_collection(name, schema=schema, index_params=indexes)

    def upsert(self, rows: list[dict[str, Any]]) -> None:
        self.ensure_collection()
        self.client.upsert(self.settings.milvus_collection, rows)

    def upsert_documents(self, rows: list[dict[str, Any]]) -> None:
        self.ensure_document_collection()
        self.client.upsert(self.settings.milvus_document_collection, rows)

    def delete_by_document(self, document_id: str) -> None:
        expression = f'document_id == "{document_id}"'
        if self.client.has_collection(self.settings.milvus_collection):
            self.client.delete(self.settings.milvus_collection, filter=expression)
        if self.client.has_collection(self.settings.milvus_document_collection):
            self.client.delete(self.settings.milvus_document_collection, filter=expression)

    def _search(
        self,
        collection: str,
        text_field: str,
        query: str,
        query_vector: list[float],
        expression: str,
        limit: int,
        output_fields: list[str],
        text_output: str,
    ) -> list[dict[str, Any]]:
        dense = AnnSearchRequest(
            data=[query_vector],
            anns_field="dense",
            param={"metric_type": "COSINE"},
            limit=limit,
            expr=expression,
        )
        sparse = AnnSearchRequest(
            data=[query],
            anns_field="sparse",
            param={"metric_type": "BM25"},
            limit=limit,
            expr=expression,
        )
        result = self.client.hybrid_search(
            collection,
            [dense, sparse],
            ranker=RRFRanker(60),
            limit=limit,
            output_fields=output_fields,
        )
        hits: list[dict[str, Any]] = []
        for hit in result[0]:
            entity = hit["entity"]
            hits.append(
                {
                    "id": str(hit[text_output]),
                    "text": entity.get(text_field),
                    "score": float(hit["distance"]),
                    "entity": entity,
                }
            )
        return hits

    def hybrid_search(
        self,
        query: str,
        query_vector: list[float],
        notebook_id: str,
        document_ids: list[str] | None = None,
        section_ids: list[str] | None = None,
        limit: int = 30,
    ) -> list[SearchHit]:
        filter_parts = [f'notebook_id == "{notebook_id}"', "is_active == true"]
        if document_ids:
            quoted = ",".join(f'"{value}"' for value in document_ids)
            filter_parts.append(f"document_id in [{quoted}]")
        if section_ids:
            quoted = ",".join(f'"{value}"' for value in section_ids)
            filter_parts.append(f"section_id in [{quoted}]")
        expression = " and ".join(filter_parts)
        raw = self._search(
            self.settings.milvus_collection,
            "content",
            query,
            query_vector,
            expression,
            limit,
            [
                "chunk_id",
                "content",
                "document_id",
                "document_version_id",
                "section_id",
                "ordinal",
                "title",
                "page_start",
                "page_end",
            ],
            "chunk_id",
        )
        hits: list[SearchHit] = []
        for hit in raw:
            entity = hit["entity"]
            hits.append(
                SearchHit(
                    chunk_id=hit["id"],
                    text=entity["content"],
                    score=hit["score"],
                    document_id=entity["document_id"],
                    document_version_id=entity["document_version_id"],
                    title=entity["title"],
                    section_id=entity.get("section_id") or None,
                    ordinal=entity.get("ordinal"),
                    page_start=entity.get("page_start"),
                    page_end=entity.get("page_end"),
                    sources=["dense", "bm25"],
                )
            )
        return hits

    def search_documents(
        self,
        query: str,
        query_vector: list[float],
        notebook_id: str,
        document_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        filter_parts = [f'notebook_id == "{notebook_id}"', "is_active == true"]
        if document_ids:
            quoted = ",".join(f'"{value}"' for value in document_ids)
            filter_parts.append(f"document_id in [{quoted}]")
        expression = " and ".join(filter_parts)
        return self._search(
            self.settings.milvus_document_collection,
            "text",
            query,
            query_vector,
            expression,
            limit,
            ["profile_id", "text", "document_id", "document_version_id", "title"],
            "profile_id",
        )
