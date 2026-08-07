# Downstream provenance

This repository is a community-maintained downstream of SASLite. No public Git
upstream or contribution channel was listed by the PyPI project when the
downstream was created.

## Imported source

- Package: `saslite`
- Version: `0.4.1`
- Source: `saslite-0.4.1.tar.gz` published on PyPI on 12 June 2026
- SHA-256: `4f351195c31d72cc0f8a4c0de1394c8c0a656984204dc8d8083f87718677550b`
- Baseline commit: `005623a`

The baseline commit is an exact import of the files in that source
distribution. Later commits contain downstream changes and regression tests.

## Current downstream changes

- Correct grouped `COUNT(DISTINCT expression)` evaluation.
- Preserve the requested aggregate alias without leaking an internal `N`
  column.
- Add regression tests for duplicate values, missing values, and complex
  expressions.

## Licensing and trademarks

The imported code remains under its MIT License; retain the copyright and
license notice when redistributing it.

SAS and other SAS Institute Inc. product and service names may be trademarks of
SAS Institute Inc. This project is independent and is not affiliated with,
endorsed by, or supported by SAS Institute Inc.
