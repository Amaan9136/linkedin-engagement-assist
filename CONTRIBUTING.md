# Contributing
Thanks for helping. Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first.

## Dev setup
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
python scripts/init_db.py
python app.py
```
Quick checks before a PR: `python -m compileall -q .` and `node --check static/js/dashboard.js` (CI runs both).

## Code map
| File | Responsibility |
|---|---|
| `app.py`, `routes/` | Flask app, authentication, CSRF, JSON API |
| `config.py` | `.env` loading and runtime setting specs and validation |
| `database/` | SQLite connection, migrations, models |
| `services/linkedin_browser.py` | Persistent Playwright context, like and comment actions, selectors |
| `services/post_collector.py` | Feed discovery and text-only extraction |
| `services/text_extractor.py` | Text rules that decide what the AI receives |
| `services/ollama_service.py`, `services/comment_service.py` | Ollama client, prompt, response validation |
| `services/engagement_service.py` | Like and comment execution, cooldowns, dashboard actions |
| `services/retry_service.py`, `services/monitoring_worker.py` | Backoff, recovery, supervisor, job loop |
| `templates/`, `static/` | Dashboard UI (no framework) |
| `docs/images/` | Diagrams used in the README |

## Adding a feature
1. New runtime settings go in `SETTING_SPECS` in `config.py`; schema changes go in a new entry in `database/migrations.py`.
2. Change state only through `database/models.py` helpers and short transactions.
3. Add an endpoint under `routes/` that validates input and returns clear errors.
4. Add UI in `templates/` and `static/js/dashboard.js`; render untrusted post text with `textContent` only.
5. Update the README if behaviour changes.

## Rules
- Keep it simple: no new framework, database or heavy dependency without discussion in an issue.
- One failure must never stop the worker: classify errors as temporary, permanent, uncertain or deferred.
- Never blindly retry an uncertain action; verify first.
- Never send images or videos to the AI; text only.
- Never log or expose secrets. Do not commit `.env`, `data/`, `logs/` or `backups/`.
- Keep PRs small; describe what changed and how you tested it.
- Contributions are licensed under the project's MIT license.
