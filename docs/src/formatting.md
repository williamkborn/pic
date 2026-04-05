# Formatting and Linting

```bash
python tools/fmt.py            # format all C and Python files
python tools/fmt.py --check    # verify formatting (CI)
bazel build --config=lint //src/... //tests/...   # clang-tidy
```

## Formatters

| Language | Tool | Config |
|---|---|---|
| C/H files | clang-format | `.clang-format` |
| Python | ruff format | `pyproject.toml` |
