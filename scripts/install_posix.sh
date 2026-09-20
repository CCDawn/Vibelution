#!/usr/bin/env bash
# One-shot macOS / Linux setup for the Vibelution workbench.
#
# Checks Python / Node / Git, creates .venv, installs Python deps, ensures web
# dependencies and the frontend build, activates project git hooks, and prints
# how to start. Idempotent: safe to re-run on an existing checkout.
#
# Usage:
#   bash scripts/install_posix.sh [--start] [--skip-frontend-build] [--skip-frontend-install]
set -euo pipefail

START=0
SKIP_FRONTEND_BUILD=0
SKIP_FRONTEND_INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --start) START=1 ;;
    --skip-frontend-build) SKIP_FRONTEND_BUILD=1 ;;
    --skip-frontend-install) SKIP_FRONTEND_INSTALL=1 ;;
    *) echo "Unknown option: $arg (supported: --start --skip-frontend-build --skip-frontend-install)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
info() { printf '    %s\n' "$1"; }
fail() { printf '\033[31mError: %s\033[0m\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
[ -f "$PROJECT_DIR/requirements.txt" ] || fail "Cannot locate Vibelution project root from: $PROJECT_DIR"
cd "$PROJECT_DIR"

OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin) PLATFORM="macOS" ;;
  Linux) PLATFORM="Linux" ;;
  *) fail "Unsupported platform: $OS_NAME (this script supports macOS and Linux)" ;;
esac

python_hint() {
  if [ "$PLATFORM" = "macOS" ]; then
    info "Install Python 3.12 via one of: brew install python@3.12 | python.org installer | uv python install 3.12"
  else
    info "Install Python 3.12 via one of: sudo apt install python3.12 python3.12-venv | python.org source | uv python install 3.12"
  fi
}

node_hint() {
  if [ "$PLATFORM" = "macOS" ]; then
    info "Install Node 18+ via: brew install node | https://nodejs.org/en/download"
  else
    info "Install Node 18+ via your distro (newer than 18) or https://nodejs.org/en/download"
  fi
}

step "Checking dependencies ($PLATFORM)"

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON_BIN="$(command -v "$candidate")"
      break
    fi
  fi
done
[ -n "$PYTHON_BIN" ] || { python_hint; fail "Python 3.11+ (3.12 recommended) is required."; }
info "Python: $("$PYTHON_BIN" --version) ($PYTHON_BIN)"

NODE_BIN="$(command -v node || true)"
if [ -n "$NODE_BIN" ]; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$NODE_MAJOR" -ge 18 ] 2>/dev/null || NODE_BIN=""
fi
[ -n "$NODE_BIN" ] || { node_hint; fail "Node.js 18+ (with npm) is required."; }
info "Node: $(node --version) / npm $(npm --version)"

command -v git >/dev/null 2>&1 || fail "Git is required (Xcode Command Line Tools on macOS, or your package manager on Linux)."
info "Git: $(git --version)"

step "Python virtual environment (.venv)"
if [ -x ".venv/bin/python" ]; then
  info "Reusing existing .venv"
else
  "$PYTHON_BIN" -m venv .venv
  info "Created .venv with $PYTHON_BIN"
fi
./.venv/bin/python -m pip install --upgrade pip -q
./.venv/bin/python -m pip install -r requirements.txt -q
info "Python dependencies installed"

step "Web dependencies (web/)"
cd web
if [ "$SKIP_FRONTEND_INSTALL" -eq 1 ]; then
  info "Skipped npm install (--skip-frontend-install)"
elif [ -d node_modules ]; then
  info "Reusing existing node_modules"
else
  npm install --no-audit --no-fund
fi

if [ "$SKIP_FRONTEND_BUILD" -eq 1 ]; then
  info "Skipped frontend build (--skip-frontend-build); the launcher builds it on first start if needed"
else
  npm run build >/dev/null
  info "Frontend built (web/dist)"
fi
cd "$PROJECT_DIR"

# npm install may rewrite web/package-lock.json metadata across npm major
# versions; the launcher requires a clean tree, so restore it when we can.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && ! git diff --quiet -- web/package-lock.json 2>/dev/null; then
  git checkout -- web/package-lock.json
  info "Restored web/package-lock.json (npm rewrote lock metadata; launcher requires a clean tree)"
fi

step "Project git hooks"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git config core.autocrlf false
  git config core.hooksPath .githooks
  chmod 755 .githooks/* 2>/dev/null || true
  info "Activated .githooks (core.hooksPath)"
else
  info "Not a git checkout; skipped"
fi

printf '\n'
printf '\033[32mSetup complete.\033[0m\n'
printf '  Start:    .venv/bin/python scripts/vibelution_launcher.py --action start --no-browser\n'
printf '  Stop:     .venv/bin/python scripts/vibelution_launcher.py --action stop\n'
printf '  Workbench: http://127.0.0.1:8000\n'
printf '  Config:   ~/Documents/Vibelution/config/config.toml (auto-created on first start)\n'
printf '  API keys: export DASHSCOPE_API_KEY=... in ~/.zshrc / ~/.bashrc (see docs/guides/install-%s.md)\n' \
  "$([ "$PLATFORM" = "macOS" ] && echo macos || echo linux)"

if [ "$START" -eq 1 ]; then
  step "Starting workbench (--start)"
  ./.venv/bin/python scripts/vibelution_launcher.py --action start --no-browser
fi
