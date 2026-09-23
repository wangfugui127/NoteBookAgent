from fastapi.testclient import TestClient

from app.main import app


def test_health_and_protected_routes_are_mounted() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        agent = client.post("/api/v1/agent/runs", json={"conversation_id": "x", "query": "q"})
        notebook = client.delete("/api/v1/notebooks/example")
        conversation = client.delete("/api/v1/conversations/example")
        datasets = client.get("/api/v1/eval/datasets")
        eval_run = client.post(
            "/api/v1/eval/datasets/example/runs", json={"notebook_id": "x"}
        )
        mcp = client.post("/mcp")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert agent.status_code == 401
    assert notebook.status_code == 401
    assert conversation.status_code == 401
    assert datasets.status_code == 401
    assert eval_run.status_code == 401
    assert mcp.status_code != 404
