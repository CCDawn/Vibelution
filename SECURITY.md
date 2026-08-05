# Security Policy

## Supported versions

Security fixes are applied on the default branch (`main`) of this repository. If you rely on a tagged release, please base reports on the latest public commit when possible.

## What is in scope

- Remote code execution or sandbox escapes via the local workbench / agent tools
- Leakage of API keys, tokens, or secrets through logs, exports, or public docs
- Authentication / control-token bypass on the local HTTP API when used as designed (loopback workbench)
- Path traversal or arbitrary file wipe outside documented Reset allowlists

## What is out of scope (by design)

- Abuse of a **user-configured** model provider or tools the operator explicitly enabled
- Secrets the operator pastes into chat, commits, or puts in tracked files
- General phishing or social engineering against repository users

## Reporting a vulnerability

**Do not** open a public issue with exploit details.

Please contact the repository owner ([@CCDawn](https://github.com/CCDawn)) privately (for example GitHub Security Advisories if enabled, or a private channel listed on the owner profile). Include:

1. Affected version / commit SHA
2. Environment (OS, install path pattern — no personal absolute paths required)
3. Reproduction steps and impact
4. Whether a fix already exists in a private patch

We will acknowledge when possible and coordinate disclosure after a fix or mitigation is available.

## Operator hygiene

- Keep LLM keys in the **external** user config / environment variables, never in the git tree
- Treat Runtime Scene bundles as sensitive diagnostics before sharing
- Prefer loopback-only binding for day-to-day local use
