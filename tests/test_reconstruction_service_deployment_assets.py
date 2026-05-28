from pathlib import Path


def test_reconstruction_service_dockerfile_exists_and_runs_api():
    text = Path("docker/reconstruction-server/Dockerfile").read_text(encoding="utf-8")

    assert "csrcqsf/biz/railwayparts/reconstruction_server" in text
    assert "celery -A celery_app worker" in text or "api.py" in text


def test_reconstruction_service_env_template_mentions_redis_and_minio():
    text = Path("docker/reconstruction-server/.env.example").read_text(encoding="utf-8")

    assert "REDIS_HOST=" in text
    assert "MINIO_ENDPOINT=" in text
    assert "RECONSTRUCTION_API_PORT=" in text


def test_reconstruction_service_run_script_uses_dedicated_image_and_env_file():
    text = Path("scripts/deployment/run_reconstruction_server.sh").read_text(encoding="utf-8")

    assert "reconstruction-server" in text
    assert "--env-file" in text
    assert "docker run -d" in text


def test_reconstruction_service_deployment_doc_mentions_reconstruction_server_url():
    text = Path("docs/deployment/reconstruction-server.md").read_text(encoding="utf-8")

    assert "RECONSTRUCTION_SERVER_URL" in text
    assert "Celery" in text
    assert "Redis" in text
