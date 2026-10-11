# Local quality gate. Run before every commit. No CI runs in the cloud.
$ErrorActionPreference = "Stop"

ruff format --check src tests
ruff check src tests
mypy src tests
pytest
