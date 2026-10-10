import pytest
from httpx import AsyncClient

from live_support import COORDINATOR, live_db_available, login_headers


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_demo_token_endpoint_removed(client: AsyncClient):
    # The old credential-less token endpoint no longer exists.
    assert (await client.get("/api/v1/auth/demo-token")).status_code in (404, 405)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/dashboard/stats", "/api/v1/map/resources", "/api/v1/evaluation/results",
                                  "/api/v1/requests", "/api/v1/resources", "/api/v1/audit/activity-feed"])
async def test_protected_endpoints_require_a_token(client: AsyncClient, path):
    response = await client.get(path)
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


async def _coordinator(client):
    err = await live_db_available()
    if err is not None:
        pytest.skip(f"Live PostgreSQL not available: {err}")
    return await login_headers(client, COORDINATOR)


@pytest.mark.asyncio
async def test_dashboard_stats_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/dashboard/stats", headers=await _coordinator(client))
    assert response.status_code == 200
    data = response.json()
    assert "resources" in data
    assert "requests" in data
    assert data["system_status"] == "ACTIVE_DISASTER_RESPONSE"


@pytest.mark.asyncio
async def test_map_resources_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/map/resources", headers=await _coordinator(client))
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_evaluation_results_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/evaluation/results", headers=await _coordinator(client))
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "ablations" in data
