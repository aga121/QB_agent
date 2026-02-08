# Repository Guidelines

## Project Structure & Module Organization
- `agent/backend/`: FastAPI backend. Entry point is `agent/backend/main.py`.
- `agent/backend/core/`: Routers and services (e.g., `user_api.py`, `agent_api.py`, `chat_api.py`, `mcp_api.py`, scheduler, DB helpers).
- `agent/ui/`: Static frontend assets mounted at `/static`. Pages live under subfolders (e.g., `chat/`, `mcp/`, `resource_panel/`, `sub_pro/`, `login/`). Shared nav lives in `agent/ui/partials/navbar.html`.
- `agent/backend/requirements.txt`: Python dependencies.
- `test_db_check.py`, `test_request.json`: ad‑hoc utilities.
- `doc/`, `CLAUDE.md`: docs and references.

## Build, Test, and Development Commands
- Create venv (Windows): `python -m venv .venv && .\.venv\Scripts\activate`
- Install deps: `pip install -r agent/backend/requirements.txt`
- Run API with reload: `uvicorn agent.backend.main:app --reload --port 8000`
- Alternate run: `python agent/backend/main.py`
- DB sanity test: `python test_db_check.py`

## Coding Style & Naming Conventions
- Python: PEP 8, 4‑space indent, `snake_case` for functions/vars, `PascalCase` for classes.
- FastAPI routers live in `agent/backend/core/*_api.py` and use `APIRouter`.
- Frontend: IDs/classes use `kebab-case`. Page‑specific JS/CSS are colocated under `agent/ui/<page>/`.
- Prefer absolute imports (e.g., `from agent.backend.core import ...`).

## Testing Guidelines
- Current tests are script‑style; run directly with `python`.
- Name new tests `test_*.py` and keep them near the code or repo root.
- Cover DB init, router responses, and scheduler status when adding features.

## Commit & Pull Request Guidelines
- Commits: clear, imperative subject (≤72 chars). Prefer Conventional Commits (e.g., `feat:`, `fix:`, `chore:`).
- PRs: include a summary, linked issues, manual test steps, and screenshots for UI changes.
- Keep diffs focused; update docs when behavior changes.

## Security & Configuration Tips
- Do not commit secrets. Configure CORS for production in `agent/backend/main.py`.
- Use environment variables for config (DB paths, API keys). A local `.env` is OK but should not be committed.
