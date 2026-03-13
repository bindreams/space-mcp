# Contributing

## Setup

Clone the repository and install in editable mode:

```sh
git clone https://github.com/bindreams/space-mcp.git
cd space-mcp
uv pip install -e .
```

## Running tests

```sh
uv run --group test pytest tests/ --ignore=tests/test_integration.py
```

## Code style

This project uses [yapf](https://github.com/google/yapf) for formatting. Configuration is in `pyproject.toml`.

```sh
uv run --group dev yapf -r -i src/
```
