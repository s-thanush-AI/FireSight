# FireSight backend

Python package `firesight`. See the repository root `README.md` and `docs/`
for full documentation.

```bash
uv sync                 # core + dev deps (no torch)
uv sync --extra yolo    # optional: Ultralytics + PyTorch
uv run pytest -q
uv run ruff check .
uv run firesight --help
```
