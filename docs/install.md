# Install

## Requirements

- Python **3.12+**
- PySide6 (Qt **6.7+**)

PySide6 is pulled in automatically by `pip` and ships pre-built wheels for
macOS, Linux, and Windows on supported Python versions, so no Qt build step
is required.

## From PyPI

```bash
pip install grafli
```

To run grafli on a `.grafli` file:

```bash
grafli my-diagram.grafli
```

Without arguments, grafli opens an empty document.

## In an isolated environment

If you don't want grafli's Qt dependency in your global site-packages,
install it with [pipx](https://pipx.pypa.io/):

```bash
pipx install grafli
```

## From source

```bash
git clone https://github.com/MisterGC/grafli.git
cd grafli
pip install -e .[dev]
pytest
```

The `dev` extra installs the test dependencies.

## Updating

```bash
pip install --upgrade grafli
```

Release notes are kept in the [changelog](https://github.com/MisterGC/grafli/blob/main/CHANGELOG.md).
