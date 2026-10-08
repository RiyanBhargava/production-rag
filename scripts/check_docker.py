"""Run repository checks in a temporary Linux container and separate test DB."""

import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    password = dotenv_values(root / ".env").get("POSTGRES_PASSWORD")
    if not password:
        raise ValueError("POSTGRES_PASSWORD missing from private .env")
    env = dict(os.environ, TEST_DATABASE_URL=f"postgresql+psycopg://rag:{password}@postgres:5432/rag_test")
    psql = ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "rag", "-d", "postgres"]
    exists = subprocess.run(
        psql + ["-tAc", "SELECT 1 FROM pg_database WHERE datname='rag_test'"],
        check=True,
        capture_output=True,
        text=True,
    )
    if exists.stdout.strip() != "1":
        subprocess.run(psql + ["-c", "CREATE DATABASE rag_test;"], check=True)
    reports = root / "data"
    reports.mkdir(exist_ok=True)
    command = (
        "set -e; uv sync --frozen; "
        "uv run --frozen pytest -q -o cache_dir=/tmp/pytest-cache; "
        "uv run --frozen ruff check app tests scripts; "
        "uv run --frozen ruff format --check app tests scripts; "
        "uv run --frozen python -m scripts.demo_evaluation"
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "root",
            "--network",
            "production-rag_default",
            "--env",
            "TEST_DATABASE_URL",
            "--env",
            "UV_PROJECT_ENVIRONMENT=/app/.venv",
            "--env",
            "UV_CACHE_DIR=/tmp/uv-cache",
            "--env",
            "RUFF_CACHE_DIR=/tmp/ruff-cache",
            "--mount",
            f"type=bind,source={root},target=/workspace,readonly",
            "--mount",
            f"type=bind,source={reports},target=/workspace/data",
            "--workdir",
            "/workspace",
            "production-rag-api",
            "/bin/sh",
            "-c",
            command,
        ],
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
