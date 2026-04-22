# Formatting and Linting

```bash
python tools/fmt.py            # format all C and Python files
python tools/fmt.py --check    # verify formatting (CI)
python tools/lint.py           # verify lizard CCN <= 10
bazel build --config=lint //src/... //tests/...   # clang-tidy
```

## Formatters

| Language | Tool | Config |
|---|---|---|
| C/H files | clang-format | `.clang-format` |
| Python | ruff format | `pyproject.toml` |

## Complexity

```bash
python tools/lint.py
python tools/lint.py --check
```

`tools/lint.py` runs `lizard` across the repository with a maximum cyclomatic
complexity number (CCN) of `10`. It excludes build artifacts, virtual
environments, and generated Bazel output trees in the same way as the other
repo-quality entrypoints.
