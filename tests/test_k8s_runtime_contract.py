import anyio

from csrcqsf.core.app import app


def test_health_endpoint_returns_ok() -> None:
    health_route = next(route for route in app.routes if getattr(route, "path", "") == "/health")

    response = anyio.run(health_route.endpoint)

    assert response == {"status": "ok", "service": "recognition"}
