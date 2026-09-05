# Security policy

## Supported version

The latest tagged release is supported. This is a local research-stage application and has not received a formal security audit.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Include the affected version, reproduction steps, impact and any suggested mitigation. Do not open a public issue for an unpatched vulnerability.

The application binds to `127.0.0.1` and does not intentionally upload match videos. Model bundles are checksum-validated, but PyTorch checkpoints can execute code during loading; only load bundles from sources you trust.
