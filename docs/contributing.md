# Contributing

Thanks for your interest. Grafli is small and opinionated — the goal of
this page is to make it easy to spin up a working environment and submit
useful changes.

## Development setup

```bash
git clone https://github.com/MisterGC/grafli.git
cd grafli
pip install -e .[dev]
pytest
```

The `dev` extra installs the test runner. The `docs` extra
(`pip install -e .[docs]`) installs MkDocs Material for previewing this
documentation site locally:

```bash
mkdocs serve
```

## Running grafli from a checkout

```bash
python -m grafli.app path/to/diagram.grafli
```

## Tests

```bash
pytest                       # all
pytest tests/test_format.py  # one file
```

On Linux CI, Qt needs a virtual framebuffer:

```bash
xvfb-run -a pytest
```

## Reporting bugs and ideas

Open issues at <https://github.com/MisterGC/grafli/issues>. Including a
minimal `.grafli` snippet that reproduces the problem makes a bug report
easy to act on.

## Pull requests

- Branch off `main`.
- Keep commits focused. One logical change per commit reads better in
  git history.
- Include or update tests when behavior changes.
- Run `pytest` before submitting.

## File format compatibility

`.grafli` is plain text and is intended to remain human-editable. When
proposing format changes, keep this constraint in mind:

- Existing files must continue to parse.
- New syntax should be a single-line element where possible.
- Keep line-level diffs meaningful — one logical edit, one diff line.
