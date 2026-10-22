# foxgrid_engine

Pure-Python direction-finding engine (numpy, pyproj; no web or database dependencies). Fuses bearings and signal
levels into the most likely transmitter location. Design and parameters: [docs/concepts/engine.md](../docs/concepts/engine.md).

```bash
uv run ruff check . && uv run mypy --strict foxgrid_engine && uv run pytest
```
