# Formatting and Linting

```bash
source sourceme                   # installs repo dev deps + git hooks
lefthook run pre-commit --all-files
lefthook run pre-push

python tools/fmt.py            # format all C and Python files
python tools/fmt.py --check    # verify formatting (CI)
python tools/lint.py           # ruff + lizard
tools/c_lint_check.sh          # clang-tidy via Bazel
```

`source sourceme` now installs `lefthook` into `python/.venv`, activates that
environment, and installs the repo hooks. The hooks are split by cost:

- `pre-commit`: format staged C/Python files and lint the staged diff
- `pre-push`: run full-repo formatting, Python lint/complexity, and C `clang-tidy`

The Python-side tools (`lefthook`, `ruff`, `lizard`) come from the repo venv.
The C-side tools still need to be on your system `PATH`: `clang-format` for
formatting and `clang-tidy` for the Bazel-backed C lint pass.

## Formatters and Linters

| Language | Tool | Config |
|---|---|---|
| C/H files | clang-format | `.clang-format` |
| C/H files | clang-tidy | `.clang-tidy` + `bazel/lint.bzl` |
| Python | ruff format / ruff check | `ruff.toml` |
| C/Python | lizard | `tools/lint.py` + `tools/lizard_baseline.txt` |

## Complexity

```bash
python tools/lint.py
python tools/lint.py --check
python tools/lint.py src/payload/hello.c python/tests/test_python_api.py
```

`tools/lint.py` runs `lizard` across the repository with a maximum cyclomatic
complexity number (CCN) of `10`. It excludes build artifacts, virtual
environments, and generated Bazel output trees in the same way as the other
repo-quality entrypoints. When you pass explicit files or directories, both
`tools/fmt.py` and `tools/lint.py` limit themselves to those paths, which is
what `lefthook` uses for the fast staged-file checks.
