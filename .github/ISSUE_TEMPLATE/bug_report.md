---
name: Bug Report
about: Report a bug to help us improve Axiom
title: "[Bug] "
labels: bug
assignees: ''
---

## Description

A clear and concise description of the bug.

## Steps to Reproduce

1. Initialise with `Matcher(n=..., mode=...)`
2. Perform operation '...'
3. Call method '...'
4. Observe error

## Expected Behaviour

What you expected to happen.

## Actual Behaviour

What actually happened. Include any error messages or tracebacks.

## Minimal Reproducible Example

```python
from axiom import Matcher

algo = Matcher(n=10, mode="basic")
# Steps to reproduce...
```

## Environment

- **OS**: [e.g., macOS 14, Ubuntu 22.04]
- **Python version**: [e.g., 3.12.1]
- **Axiom version**: [e.g., 0.5.0]
- **Installation method**: [e.g., pip install -e ".[dev]"]

## Additional Context

Add any other context, screenshots, or logs about the problem here.

## Checklist

- [ ] I have searched existing issues to ensure this is not a duplicate
- [ ] I have included a minimal reproducible example
- [ ] I have included the Python and Axiom versions
- [ ] I have run the test suite (`pytest tests/ -v`) and confirmed the issue persists