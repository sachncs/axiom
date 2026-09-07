# Contributing to Axiom

Thank you for your interest in contributing to Axiom! This document provides guidelines and information for contributors.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Branch Naming](#branch-naming)
- [Commit Conventions](#commit-conventions)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Running Tests](#running-tests)
- [Documentation](#documentation)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/fully-dynamic-maximal-matching.git
   cd fully-dynamic-maximal-matching
   ```
3. **Set up** the development environment (see below)
4. Create a feature branch and start contributing

## Development Setup

### Prerequisites

- Python ≥ 3.10
- Git

### Installation

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate      # Windows

# Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify installation
pytest tests/ -v
```

### Available Commands

| Command | Description |
|---------|-------------|
| `pytest tests/ -v` | Run the test suite |
| `pytest --cov=axiom tests/` | Run tests with coverage |
| `mypy src/axiom/` | Run type checking |
| `ruff check src/axiom/ tests/ scripts/` | Run linting |
| `ruff format src/ tests/ scripts/` | Auto-format code |
| `axiom --n 20 --mode basic` | Run the CLI demo |

## Branch Naming

Use descriptive branch names with a prefix:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feat/` | New features | `feat/batch-updates` |
| `fix/` | Bug fixes | `fix/rematch-stale-lambda` |
| `docs/` | Documentation | `docs/architecture-guide` |
| `refactor/` | Code refactoring | `refactor/invariants-module` |
| `test/` | Tests | `test/multilevel-stress` |
| `chore/` | Maintenance | `chore/update-deps` |

## Commit Conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Types

- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation only changes
- **style**: Formatting, missing semi-colons, etc (no code change)
- **refactor**: A code change that neither fixes a bug nor adds a feature
- **perf**: A code change that improves performance
- **test**: Adding missing tests or correcting existing tests
- **chore**: Changes to the build process or auxiliary tools

### Examples

```
feat: add batch update support for edge insertions

fix: prevent phantom edges from stale lambda lists

docs: add architecture overview to docs/

test: add stress tests for multi-level mode

chore: update pytest to 8.x
```

## Pull Request Process

1. **Update your fork** to the latest upstream:
   ```bash
   git remote add upstream https://github.com/sachncs/fully-dynamic-maximal-matching.git
   git fetch upstream
   git checkout master
   git merge upstream/master
   ```

2. **Create a feature branch** from `master`:
   ```bash
   git checkout -b feat/my-feature
   ```

3. **Make your changes** following the coding standards below

4. **Run the full check suite** before submitting:
   ```bash
   ruff check src/axiom/ tests/ scripts/
   mypy src/axiom/
   pytest tests/ -v
   ```

5. **Push** your branch and open a pull request

6. **Fill in the PR template** with:
   - Summary of changes
   - Related issue (if any)
   - Testing performed
   - Checklist completion

### PR Review Criteria

PRs will be reviewed for:

- Correctness and test coverage
- Type annotation completeness
- Documentation updates (if applicable)
- Adherence to coding standards
- No regressions in existing tests

## Coding Standards

### Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions
- Maximum line length: 88 characters (ruff default)
- Use type annotations for all public functions and methods
- Use `from __future__ import annotations` for forward references

### Type Annotations

```python
def example(u: int, v: int) -> bool:
    """Example with full type annotations."""
    ...
```

### Docstrings

Use Google-style docstrings:

```python
def example(u: int, v: int) -> bool:
    """Check if an edge exists between two vertices.

    Args:
        u: First vertex index.
        v: Second vertex index.

    Returns:
        True if the edge exists, False otherwise.

    Raises:
        ValueError: If either vertex is out of range.
    """
    ...
```

### Imports

Organise imports in the following order:

1. Standard library
2. Third-party packages
3. Local modules

Separate each group with a blank line. Use absolute imports.

## Running Tests

### Full Test Suite

```bash
pytest tests/ -v
```

### With Coverage

```bash
pytest --cov=axiom --cov-report=term-missing tests/
```

### Specific Test Classes

```bash
pytest tests/test_axiom.py::TestMatcher -v
```

### Property-Based Tests

The test suite includes Hypothesis-based property tests. These run automatically with pytest.

## Documentation

- Update `README.md` if adding new features or changing usage patterns
- Add docstrings to all public functions and classes
- Update `CHANGELOG.md` following the [Keep a Changelog](https://keepachangelog.com/) format
- Ensure `docs/` files are updated for architectural changes

### Changelog Format

```markdown
## [version] - YYYY-MM-DD

### Added
- New feature description

### Changed
- Changed feature description

### Fixed
- Bug fix description

### Removed
- Removed feature description
```

## Questions?

If you have questions about contributing, feel free to open a [Discussion](https://github.com/sachncs/fully-dynamic-maximal-matching/discussions) or reach out to the maintainers.
