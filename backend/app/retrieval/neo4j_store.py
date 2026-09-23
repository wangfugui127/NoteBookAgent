from typing import Any

from neo4j import AsyncGraphDatabase

from app.core.config import Settings


class Neo4jStore:
    def __init__(self, settings: Settings) -> None:
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )

    async def verify(self) -> bool:
        try:
            await self.driver.verify_connectivity()
            return True
        except Exception:
            return False

    async def create_constraints(self) -> None:
        statements = [
            "CREATE CONSTRAINT document_version_id IF NOT EXISTS "
            "FOR (n:DocumentVersion) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (n:Entity) REQUIRE n.key IS UNIQUE",
            "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (n:Section) REQUIRE n.id IS UNIQUE",
        ]
        async with self.driver.session() as session:
            for statement in statements:
                await session.run(statement)

    async def upsert_chunk(
        self,
        notebook_id: str,
        document_version_id: str,
        chunk_id: str,
        section: dict[str, Any],
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        previous_chunk_id: str | None = None,
    ) -> None:
        query = """
        MERGE (d:DocumentVersion {id: $document_version_id})
        SET d.notebook_id = $notebook_id
        MERGE (c:Chunk {id: $chunk_id})
        MERGE (d)-[:HAS_CHUNK]->(c)
        MERGE (s:Section {id: $section_id})
        SET s.title = $section_title, s.notebook_id = $notebook_id,
            s.document_version_id = $document_version_id
        MERGE (d)-[:HAS_SECTION]->(s)
        MERGE (s)-[:HAS_CHUNK]->(c)
        WITH c
        UNWIND $entities AS entity
        MERGE (e:Entity {key: $notebook_id + ':' + entity.key})
        SET e.name = entity.name, e.kind = entity.kind
        FOREACH (_ IN CASE WHEN entity.kind = 'Method' THEN [1] ELSE [] END | SET e:Method)
        FOREACH (_ IN CASE WHEN entity.kind = 'Dataset' THEN [1] ELSE [] END | SET e:Dataset)
        FOREACH (_ IN CASE WHEN entity.kind = 'Metric' THEN [1] ELSE [] END | SET e:Metric)
        FOREACH (_ IN CASE WHEN entity.kind = 'Paper' THEN [1] ELSE [] END | SET e:Paper)
        MERGE (c)-[:MENTIONS]->(e)
        """
        async with self.driver.session() as session:
            await session.run(
                query,
                notebook_id=notebook_id,
                document_version_id=document_version_id,
                chunk_id=chunk_id,
                section_id=section["id"],
                section_title=section["title"],
                entities=entities,
            )
            if previous_chunk_id:
                await session.run(
                    """
                    MATCH (previous:Chunk {id: $previous_chunk_id})
                    MATCH (current:Chunk {id: $chunk_id})
                    MERGE (previous)-[:NEXT_CHUNK]->(current)
                    """,
                    previous_chunk_id=previous_chunk_id,
                    chunk_id=chunk_id,
                )
            allowed_relation_types = {
                "USES_METHOD",
                "USES_DATASET",
                "MEASURES_METRIC",
                "CITES",
                "COMPARES_WITH",
                "SUPPORTS",
                "CONTRADICTS",
                "RELATED_TO",
            }
            for relation in relations:
                relation_type = str(relation.get("kind") or "RELATED_TO").upper()
                if relation_type not in allowed_relation_types:
                    relation_type = "RELATED_TO"
                await session.run(
                    f"""
                    MATCH (a:Entity {{key: $notebook_id + ':' + $source}})
                    WITH a
                    MATCH (b:Entity {{key: $notebook_id + ':' + $target}})
                    MERGE (a)-[r:{relation_type} {{chunk_id: $chunk_id}}]->(b)
                    SET r.confidence = $confidence,
                        r.notebook_id = $notebook_id,
                        r.document_version_id = $document_version_id,
                        r.evidence_chunk_ids = [$chunk_id],
                        r.extractor_model = $extractor_model,
                        r.extractor_version = $extractor_version
                    """,
                    source=relation["source"],
                    target=relation["target"],
                    kind=relation.get("kind", "RELATED_TO"),
                    confidence=relation.get("confidence", 0.5),
                    notebook_id=notebook_id,
                    chunk_id=chunk_id,
                    document_version_id=document_version_id,
                    extractor_model=relation.get("extractor_model", "unknown"),
                    extractor_version=relation.get("extractor_version", "1"),
                )

    async def expand(self, notebook_id: str, entity_names: list[str], limit: int = 30) -> list[str]:
        if not entity_names:
            return []
        query = """
        MATCH (seed:Entity)
        WHERE toLower(seed.name) IN $names
        MATCH (seed)-[*1..2]-(related:Entity)<-[:MENTIONS]-(chunk:Chunk)
              <-[:HAS_CHUNK]-(doc:DocumentVersion)
        WHERE doc.notebook_id = $notebook_id
        RETURN DISTINCT chunk.id AS chunk_id
        LIMIT $limit
        """
        async with self.driver.session() as session:
            result = await session.run(
                query,
                names=[name.lower() for name in entity_names],
                notebook_id=notebook_id,
                limit=limit,
            )
            return [record["chunk_id"] async for record in result]

    async def delete_document_version(self, document_version_id: str) -> None:
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (d:DocumentVersion {id: $document_version_id})
                OPTIONAL MATCH (d)-[:HAS_SECTION|HAS_CHUNK]->(child)
                DETACH DELETE child, d
                """,
                document_version_id=document_version_id,
            )

    async def close(self) -> None:
        await self.driver.close()
