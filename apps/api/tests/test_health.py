from bookmarks_api import API_CONTRACT_VERSION


def test_health_reports_database_reachable(client):
    r = client.get("/api/v2/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["version"]


def test_health_exposes_the_contract_version(client):
    """The browser asserts this at startup, so it must be present and stable."""
    body = client.get("/api/v2/health").json()
    assert body["contract"] == API_CONTRACT_VERSION


def test_contract_version_matches_the_mounted_path(client):
    """`contract` and the `/api/vN` prefix describe the same thing and must agree."""
    body = client.get("/api/v2/health").json()
    assert f"/api/v{body['contract']}/health" == "/api/v2/health"


def test_release_version_and_contract_version_are_independent(client):
    """A release bump must not move the contract, and vice versa."""
    body = client.get("/api/v2/health").json()
    assert isinstance(body["contract"], int)
    assert isinstance(body["version"], str)
    assert body["version"] != str(body["contract"])
