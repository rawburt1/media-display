# Contributing

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r vinyl_recognizer/requirements.txt
pip install pytest
```

## Running tests

```bash
pytest
```

This runs both the main `tests/` suite and `vinyl_recognizer/tests/`. All
tests must pass before a PR can be merged - CI runs the same command on
every push and pull request (see `.github/workflows/tests.yml`), and the
`test` check is required on `master`.

## Adding a new source/output/idle wallpaper source/enricher

See the "Extending with new sources/outputs" section in `README.md` for the
steps (config dataclass, module, registration in `__main__.py`). A few
conventions to follow:

- Each source's `get_now_playing()` must catch its own connection errors
  and return `None` rather than raising, so one unreachable source never
  breaks the polling loop.
- Add tests for new sources/outputs/enrichers following the existing
  `tests/test_*.py` files as a template - they mock the network calls
  rather than hitting real services.
- Update `config.example.yaml` and the "Configuration" section of
  `README.md` with any new config fields and setup steps (API keys, auth
  commands, etc).

## Pull requests

- Keep PRs focused on a single change.
- Make sure `pytest` passes locally before pushing.
