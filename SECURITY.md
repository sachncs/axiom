# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.5.x   | :white_check_mark: |
| 0.4.x   | :white_check_mark: |
| < 0.4   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability within Axiom, please send an email to **sachncs@gmail.com**. All security vulnerabilities will be promptly addressed.

**Please do not report security vulnerabilities through public GitHub issues.**

### What to Include

When reporting a vulnerability, please include:

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Suggested fix (if any)

### Response Expectations

- **Acknowledgement**: Within 48 hours of your report
- **Assessment**: Within 1 week, we will assess the severity and validity
- **Fix**: Critical vulnerabilities will be patched as soon as possible
- **Disclosure**: We will coordinate with you on the timing of public disclosure

## Disclosure Policy

We follow coordinated disclosure:

1. **Report received** &mdash; We acknowledge receipt within 48 hours.
2. **Investigation** &mdash; We investigate and confirm the vulnerability.
3. **Fix developed** &mdash; We develop and test a fix.
4. **Release** &mdash; We release the fix in a patch version.
5. **Disclosure** &mdash; We publish a security advisory after the fix is available.

We ask that you give us reasonable time to address the issue before public disclosure.

## Security Best Practices

When using Axiom in production:

- Keep Python and dependencies up to date.
- Run with the minimum required privileges.
- Monitor for unexpected behaviour in matching operations.
- Validate all input data before passing to the algorithm.
- Use `strict=True` on `Adjacency.add_edge`/`remove_edge` if your input is untrusted.

## Scope

This security policy applies to:

- The `axiom` Python package
- The source code in this repository
- CI/CD workflows

It does **not** apply to:

- Third-party dependencies (report to their maintainers)
- Issues in the original paper's algorithm design