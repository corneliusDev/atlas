"""Infra checks: compose structure, host-ollama override, Dockerfiles, nginx config.

Run from the repo root:  api/.venv/bin/python -m pytest -q infra/tests
Needs the docker CLI (compose config renders locally; the nginx test runs nginx:1.27-alpine).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HAS_DOCKER = shutil.which("docker") is not None
needs_docker = pytest.mark.skipif(not HAS_DOCKER, reason="docker CLI not available")

# Keep rendering independent of a developer's local .env.
_CLEAN_ENV = {
    k: v
    for k, v in os.environ.items()
    if k not in {"VAULT_PATH", "ANTHROPIC_API_KEY", "ATLAS_LLM_MODEL", "ATLAS_EMBEDDINGS_ONLY",
                 "OLLAMA_URL", "HOST_OLLAMA_URL", "ATLAS_WEB_PORT", "COMPOSE_FILE", "COMPOSE_PROFILES"}
}


def render(*files: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    args = ["docker", "compose", "-p", "atlas-infra-test", "--project-directory", str(ROOT),
            "--env-file", os.devnull]
    for f in files:
        args += ["-f", str(ROOT / f)]
    args += ["config", "--format", "json"]
    out = subprocess.run(args, check=True, capture_output=True, text=True,
                         env={**_CLEAN_ENV, **(env or {})})
    result: dict[str, Any] = json.loads(out.stdout)
    return result


@pytest.fixture(scope="module")
def base() -> dict[str, Any]:
    return render("docker-compose.yml")


@pytest.fixture(scope="module")
def host_ollama() -> dict[str, Any]:
    return render("docker-compose.yml", "docker-compose.host-ollama.yml")


def _deps(svc: dict[str, Any]) -> dict[str, str]:
    return {name: d["condition"] for name, d in svc.get("depends_on", {}).items()}


# ---- compose: services, images, health ----------------------------------------------------
@needs_docker
def test_services_and_images(base: dict[str, Any]) -> None:
    s = base["services"]
    assert set(s) == {"db", "ollama", "ollama-init", "api", "worker", "web"}
    assert s["db"]["image"] == "pgvector/pgvector:pg16"
    assert s["ollama"]["image"] == "ollama/ollama"
    assert s["ollama-init"]["image"] == "ollama/ollama"
    assert s["api"]["build"]["context"] == str(ROOT / "api")
    assert s["worker"]["build"]["context"] == str(ROOT / "api")
    assert s["api"]["image"] == s["worker"]["image"]  # one image for api + worker
    assert s["worker"]["command"] == ["python", "-m", "atlas.worker"]
    assert s["web"]["build"]["context"] == str(ROOT / "web")


@needs_docker
def test_healthchecks_and_dependency_conditions(base: dict[str, Any]) -> None:
    s = base["services"]
    for name in ("db", "ollama", "api"):
        assert s[name]["healthcheck"]["test"], name
    assert "pg_isready" in " ".join(s["db"]["healthcheck"]["test"])
    assert _deps(s["ollama-init"]) == {"ollama": "service_healthy"}
    assert _deps(s["api"])["db"] == "service_healthy"
    assert _deps(s["worker"]) == {
        "db": "service_healthy",
        "api": "service_healthy",
        "ollama-init": "service_completed_successfully",
    }
    assert _deps(s["web"]) == {"api": "service_healthy"}


@needs_docker
def test_ollama_init_pulls_embedding_model_once(base: dict[str, Any]) -> None:
    init = base["services"]["ollama-init"]
    assert init["entrypoint"] == ["ollama"]
    assert init["command"] == ["pull", "nomic-embed-text"]
    assert init["environment"]["OLLAMA_HOST"] == "http://ollama:11434"
    assert init.get("restart", "no") == "no"


# ---- compose: environment, volumes, ports -------------------------------------------------
@needs_docker
def test_app_environment(base: dict[str, Any]) -> None:
    for name in ("api", "worker"):
        env = base["services"][name]["environment"]
        assert env["DATABASE_URL"] == "postgresql://atlas:atlas@db:5432/atlas"
        assert env["OLLAMA_URL"] == "http://ollama:11434"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ATLAS_LLM_MODEL"] == "claude-opus-5-5"
        assert env["ATLAS_EMBEDDINGS_ONLY"] == "false"
        assert env["VAULT_ROOT"] == "/vault"
        assert env["UPLOADS_ROOT"] == "/uploads"


@needs_docker
def test_env_overrides_flow_through() -> None:
    cfg = render("docker-compose.yml", env={
        "ANTHROPIC_API_KEY": "sk-test", "ATLAS_LLM_MODEL": "other-model",
        "ATLAS_EMBEDDINGS_ONLY": "true", "VAULT_PATH": "/tmp/somevault", "ATLAS_WEB_PORT": "3999",
    })
    env = cfg["services"]["worker"]["environment"]
    assert (env["ANTHROPIC_API_KEY"], env["ATLAS_LLM_MODEL"], env["ATLAS_EMBEDDINGS_ONLY"]) == (
        "sk-test", "other-model", "true")
    vault = next(v for v in cfg["services"]["api"]["volumes"] if v["target"] == "/vault")
    assert vault["source"] == "/tmp/somevault"
    assert cfg["services"]["web"]["ports"][0]["published"] == "3999"


@needs_docker
def test_vault_read_only_and_uploads_volume(base: dict[str, Any]) -> None:
    for name in ("api", "worker"):
        vols = {v["target"]: v for v in base["services"][name]["volumes"]}
        assert vols["/vault"]["type"] == "bind"
        assert vols["/vault"]["read_only"] is True
        assert vols["/vault"]["source"] == str(ROOT / "samples" / "vault")
        assert vols["/uploads"]["type"] == "volume"
        assert vols["/uploads"]["source"] == "uploads"
    assert {"pgdata", "ollama", "uploads"} <= set(base["volumes"])
    db_vols = {v["target"]: v for v in base["services"]["db"]["volumes"]}
    assert db_vols["/var/lib/postgresql/data"]["source"] == "pgdata"


@needs_docker
def test_only_web_is_published_and_only_on_localhost(base: dict[str, Any]) -> None:
    for name, svc in base["services"].items():
        if name != "web":
            assert not svc.get("ports"), f"{name} must not publish ports"
    (port,) = base["services"]["web"]["ports"]
    assert port["host_ip"] == "127.0.0.1"
    assert port["published"] == "3000"
    assert port["target"] == 80


# ---- host-ollama override -----------------------------------------------------------------
@needs_docker
def test_host_ollama_override(host_ollama: dict[str, Any]) -> None:
    s = host_ollama["services"]
    assert "ollama" not in s and "ollama-init" not in s  # moved to an inactive profile
    for name in ("api", "worker"):
        assert s[name]["environment"]["OLLAMA_URL"] == "http://host.docker.internal:11434"
        assert "host.docker.internal=host-gateway" in s[name]["extra_hosts"] or \
            "host.docker.internal:host-gateway" in s[name]["extra_hosts"]
        assert "ollama" not in _deps(s[name]) and "ollama-init" not in _deps(s[name])
    assert _deps(s["worker"]) == {"db": "service_healthy", "api": "service_healthy"}


@needs_docker
def test_host_ollama_bundled_profile_still_available() -> None:
    cfg = render("docker-compose.yml", "docker-compose.host-ollama.yml",
                 env={"COMPOSE_PROFILES": "bundled-ollama"})
    assert {"ollama", "ollama-init"} <= set(cfg["services"])


# ---- Dockerfiles --------------------------------------------------------------------------
def _from_lines(path: Path) -> list[str]:
    return re.findall(r"^FROM\s+(\S+)", path.read_text(), flags=re.M)


def test_api_dockerfile() -> None:
    text = (ROOT / "api" / "Dockerfile").read_text()
    froms = _from_lines(ROOT / "api" / "Dockerfile")
    assert froms == ["python:3.12-slim", "python:3.12-slim"]  # multi-stage
    users = re.findall(r"^USER\s+(\S+)", text, flags=re.M)
    assert users and not users[-1].startswith(("root", "0"))
    assert "python -m atlas.store.migrate" in text and "uvicorn atlas.http.app:app" in text
    assert "--port 8000" in text


def test_web_dockerfile() -> None:
    froms = _from_lines(ROOT / "web" / "Dockerfile")
    assert froms == ["node:22-alpine", "nginx:1.27-alpine"]
    text = (ROOT / "web" / "Dockerfile").read_text()
    assert "/etc/nginx/conf.d/default.conf" in text
    assert "/app/dist /usr/share/nginx/html" in text


def test_nginx_conf_routes() -> None:
    text = (ROOT / "web" / "nginx.conf").read_text()
    assert "listen 80;" in text
    assert re.search(r"location /api/ \{[^}]*proxy_pass \$atlas_api;", text, flags=re.S)
    assert "set $atlas_api http://api:8000;" in text
    assert "try_files $uri $uri/ /index.html;" in text


@needs_docker
def test_nginx_conf_is_valid() -> None:
    """`nginx -t` inside the real runtime image (no network needed thanks to the resolver)."""
    out = subprocess.run(
        ["docker", "run", "--rm", "--name", "atlas-track-a-nginx-t",
         "-v", f"{ROOT / 'web' / 'nginx.conf'}:/etc/nginx/conf.d/default.conf:ro",
         "nginx:1.27-alpine", "nginx", "-t"],
        capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "syntax is ok" in out.stderr


def test_env_example_lists_compose_variables() -> None:
    text = (ROOT / ".env.example").read_text()
    for var in ("VAULT_PATH", "ANTHROPIC_API_KEY", "ATLAS_LLM_MODEL", "ATLAS_EMBEDDINGS_ONLY"):
        assert re.search(rf"^{var}=", text, flags=re.M), var
