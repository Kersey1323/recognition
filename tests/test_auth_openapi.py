from fastapi import FastAPI

from csrcqsf.core.auth.middleware import configure_openapi_security


def test_openapi_declares_global_bearer_security_except_health():
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/business")
    async def business():
        return {"status": "ok"}

    configure_openapi_security(app, health_path="/health")
    schema = app.openapi()

    assert schema["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "SGO Token",
    }
    assert schema["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/health"]["get"]["security"] == []
