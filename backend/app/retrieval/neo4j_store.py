from typing import Any

from neo4j import AsyncGraphDatabase

from app.core.config import Settings

RELATION_TYPES = (
    "USES_METHOD",
    "USES_DATASET",
    "REPORTS_RESULT",
    "MEASURES",
    "CITES",
    "COMPARES_WITH",
    "RELATED_TO",
)

EXPERIMENT_DETAIL = """
OPTIONAL MATCH (e)-[um:USES_METHOD]->(m:Method)
OPTIONAL MATCH (e)-[ud:USES_DATASET]->(ds:Dataset)
OPTIONAL MATCH (e)-[rr:REPORTS_RESULT]->(res:Result)
OPTIONAL MATCH (res)-[mm:MEASURES]->(mt:Metric)
RETURN p.id AS paper_id, p.title AS paper_title,
       e.key AS experiment_key, e.name AS experiment_name,
       collect(DISTINCT CASE WHEN m IS NULL THEN NULL ELSE
           {name: m.name, evidence: um.evidence_chunk_ids} END) AS methods,
       collect(DISTINCT CASE WHEN ds IS NULL THEN NULL ELSE
           {name: ds.name, evidence: ud.evidence_chunk_ids} END) AS datasets,
       collect(DISTINCT CASE WHEN res IS NULL THEN NULL ELSE
           {name: res.name, evidence: rr.evidence_chunk_ids} END) AS results,
       collect(DISTINCT CASE WHEN mt IS NULL THEN NULL ELSE
           {name: mt.name, evidence: mm.evidence_chunk_ids} END) AS metrics
"""


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
            "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (n:Paper) REQUIRE n.id IS UNIQUE",
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
        paper_id: str,
        paper_title: str,
        chunk_id: str,
        section: dict[str, Any],
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> None:
        node_query = """
        MERGE (p:Paper {id: $paper_id})
        SET p.title = $paper_title, p.notebook_id = $notebook_id
        MERGE (d:DocumentVersion {id: $document_version_id})
        SET d.notebook_id = $notebook_id
        MERGE (p)-[:HAS_VERSION]->(d)
        MERGE (c:Chunk {id: $chunk_id})
        SET c.notebook_id = $notebook_id
        MERGE (d)-[:HAS_CHUNK]->(c)
        MERGE (s:Section {id: $section_id})
        SET s.title = $section_title, s.notebook_id = $notebook_id,
            s.document_version_id = $document_version_id
        MERGE (d)-[:HAS_SECTION]->(s)
        MERGE (s)-[:HAS_CHUNK]->(c)
        WITH p, c, s
        UNWIND $entities AS entity
        MERGE (e:Entity {key: $notebook_id + ':' + entity.key})
        SET e.name = entity.name, e.kind = entity.kind, e.notebook_id = $notebook_id
        FOREACH (_ IN CASE WHEN entity.kind = 'Experiment' THEN [1] ELSE [] END |
            SET e:Experiment)
        FOREACH (_ IN CASE WHEN entity.kind = 'Method' THEN [1] ELSE [] END |
            SET e:Method)
        FOREACH (_ IN CASE WHEN entity.kind = 'Dataset' THEN [1] ELSE [] END |
            SET e:Dataset)
        FOREACH (_ IN CASE WHEN entity.kind = 'Metric' THEN [1] ELSE [] END |
            SET e:Metric)
        FOREACH (_ IN CASE WHEN entity.kind = 'Result' THEN [1] ELSE [] END |
            SET e:Result)
        FOREACH (_ IN CASE WHEN entity.kind = 'Paper' THEN [1] ELSE [] END |
            SET e:Paper)
        FOREACH (_ IN CASE WHEN entity.kind = 'Experiment' THEN [1] ELSE [] END |
            MERGE (p)-[:HAS_EXPERIMENT]->(e))
        """
        async with self.driver.session() as session:
            await session.run(
                node_query,
                notebook_id=notebook_id,
                document_version_id=document_version_id,
                paper_id=paper_id,
                paper_title=paper_title,
                chunk_id=chunk_id,
                section_id=section["id"],
                section_title=section["title"],
                entities=entities,
            )
            for relation in relations:
                relation_type = str(relation.get("kind") or "RELATED_TO").upper()
                if relation_type not in RELATION_TYPES:
                    continue
                await session.run(
                    f"""
                    MATCH (a:Entity {{key: $notebook_id + ':' + $source}})
                    MATCH (b:Entity {{key: $notebook_id + ':' + $target}})
                    MERGE (a)-[r:{relation_type}]->(b)
                    SET r.notebook_id = $notebook_id,
                        r.document_version_id = $document_version_id,
                        r.confidence = $confidence,
                        r.extractor_model = $extractor_model,
                        r.extractor_version = $extractor_version,
                        r.evidence_chunk_ids = CASE
                            WHEN r.evidence_chunk_ids IS NULL THEN [$chunk_id]
                            WHEN $chunk_id IN r.evidence_chunk_ids THEN r.evidence_chunk_ids
                            ELSE r.evidence_chunk_ids + [$chunk_id] END
                    """,
                    source=relation["source"],
                    target=relation["target"],
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
        WHERE seed.notebook_id = $notebook_id AND toLower(seed.name) IN $names
        MATCH (seed)-[rels*1..2]-(:Entity)
        UNWIND rels AS r
        WITH r WHERE r.evidence_chunk_ids IS NOT NULL
        UNWIND r.evidence_chunk_ids AS cid
        RETURN DISTINCT cid AS chunk_id
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

    async def search_experiments(
        self, notebook_id: str, entity_names: list[str], limit: int = 10
    ) -> list[dict[str, Any]]:
        if entity_names:
            query = f"""
            MATCH (seed:Entity)
            WHERE seed.notebook_id = $notebook_id AND toLower(seed.name) IN $names
            MATCH (seed)-[*1..3]-(e:Experiment)
            MATCH (p:Paper)-[:HAS_EXPERIMENT]->(e)
            WITH DISTINCT p, e
            {EXPERIMENT_DETAIL}
            LIMIT $limit
            """
        else:
            query = f"""
            MATCH (p:Paper)-[:HAS_EXPERIMENT]->(e:Experiment)
            WHERE p.notebook_id = $notebook_id
            WITH p, e
            {EXPERIMENT_DETAIL}
            LIMIT $limit
            """
        async with self.driver.session() as session:
            result = await session.run(
                query,
                names=[name.lower() for name in entity_names],
                notebook_id=notebook_id,
                limit=limit,
            )
            items: list[dict[str, Any]] = []
            async for record in result:
                items.append(
                    {
                        "paper_id": record["paper_id"],
                        "paper_title": record["paper_title"],
                        "experiment_key": record["experiment_key"],
                        "experiment_name": record["experiment_name"],
                        "methods": [item for item in record["methods"] if item],
                        "datasets": [item for item in record["datasets"] if item],
                        "results": [item for item in record["results"] if item],
                        "metrics": [item for item in record["metrics"] if item],
                    }
                )
            return items

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
