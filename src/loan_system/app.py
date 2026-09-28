"""Điểm vào cho uvicorn: `uv run uvicorn loan_system.app:app`."""

from loan_system.main import create_app

app = create_app()
