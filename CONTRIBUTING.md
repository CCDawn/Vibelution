# Contributing to Vibelution

Thanks for helping improve Vibelution — bilingual (中文 / English) PRs and issues are welcome.

感谢关注 Vibelution。Issue / Discussion / PR 中英文均可。

## Before you start

- Product intent: [README.md](README.md) · [docs/product/README.md](docs/product/README.md)
- Coding agent / standards: [docs/guides/README.md](docs/guides/README.md) · [docs/standards/README.md](docs/standards/README.md)
- If present in your clone: [AGENTS.md](AGENTS.md)
- **Never** commit API keys, private provider URLs, absolute personal paths, chat dumps, or runtime data under `workspace/` / `.runtime/`

## Development setup

1. Python **3.11+** (3.12 recommended): project venv + `pip install -r requirements.txt`
2. Frontend: `cd web && npm install`（launcher 也可自动引导）
3. Start:
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts/vibelution_launcher.ps1 -Action start`
   - macOS / Linux: `python scripts/vibelution_launcher.py --action start --no-browser`

## Pull requests

- Prefer **small, focused** PRs: problem → approach → how you verified
- Match tests to the surface you touch: `tests/` (Python), `cd web && npm test` / `npm run build` (UI)
- Commit messages: short imperative (what + why)
- 中文说明也可；标题建议带清晰英文摘要，方便检索

## Good first contributions

- Docs / README clarity, i18n copy, accessibility
- UI polish on Chat / Teams / Git surfaces with screenshots of **demo data only**
- Tests for existing behavior (no secret fixtures)

## Security

Report vulnerabilities that may expose secrets or enable remote code execution **privately** to the repository owner — do not open a public issue with exploit details.

安全问题请私下联系维护者，勿在公开 Issue 中粘贴可利用细节。
