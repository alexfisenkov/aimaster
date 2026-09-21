# Telegram macOS transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a macOS-only Telegram transport and authenticated Mini App that reuse the existing AI Мастерская workspace.

**Architecture:** Extend the existing owner-only Bot API controller with a durable inbox, inline project/menu actions, and a local Codex bridge. Add a loopback Mini App gateway that validates Telegram `initData`; an optional cloudflared launcher supplies HTTPS without exposing Studio directly.

**Tech Stack:** Python 3.11 standard library, existing Creator Studio SQLite/store/ledger, Telegram Bot API, existing static dashboard, optional `cloudflared` subprocess.

**Spec:** `docs/superpowers/specs/2026-09-21-telegram-mac-transport.md`

## Global Constraints

- macOS only; do not claim Windows support.
- Keep workspace/state/ledger canonical; no duplicate project model.
- Never log or pass the bot token in URLs, argv, prompts, or public API responses.
- All writes use existing authoring/ledger doors and remain owner-only.
- No live Telegram connection, paid generation, or real token during tests.
- TDD: each new behavior gets a failing test before implementation.

### Task 1: Durable transport state and secure token setup

**Files:**
- Modify: `skills/aimaster/studio/telegram_bot.py`
- Modify: `skills/aimaster/scripts/creator_studio_bot.py`
- Create: `skills/aimaster/scripts/creator_studio_telegram.py`
- Test: `skills/aimaster/scripts/test_telegram_transport.py`

- [ ] Write failing tests for owner pairing, durable inbox/dequeue, idempotent update handling, hidden token input validation, and project menu payloads.
- [ ] Run the test file and confirm missing transport APIs fail.
- [ ] Implement SQLite inbox/outbox and local secret-store abstraction with Keychain detection plus mode-0600 fallback.
- [ ] Add setup/run CLI entrypoint without network in import or help paths.
- [ ] Run focused tests, then the existing suite.

### Task 2: Codex local bridge

**Files:**
- Create: `skills/aimaster/studio/agent_bridge.py`
- Modify: `skills/aimaster/scripts/creator_studio_telegram.py`
- Test: `skills/aimaster/scripts/test_agent_bridge.py`

- [ ] Write failing tests for prompt construction, workspace/project scoping, secret-free argv, timeout and outcome-unknown handling.
- [ ] Implement an injectable runner using `codex exec` through stdin and sanitized Telegram output; unavailable CLI produces setup guidance.
- [ ] Process one inbox item at a time and persist idempotency/outcome.
- [ ] Run focused bridge tests with a fake subprocess.

### Task 3: Telegram callbacks and media intake

**Files:**
- Modify: `skills/aimaster/scripts/creator_studio_bot.py`
- Modify: `skills/aimaster/studio/telegram_bot.py`
- Test: `skills/aimaster/scripts/test_telegram_transport.py`

- [ ] Write failing tests for callback routing, project selection, text/voice/photo/video/document envelopes, and non-owner rejection.
- [ ] Add Bot API callback, inline keyboard, `getFile`, and bounded media-download methods; validate MIME/size before workspace media writes.
- [ ] Route voice notes to local transcription through the bridge prompt and never claim transcription before an artifact exists.
- [ ] Run focused fake-API tests.

### Task 4: Authenticated Mini App gateway

**Files:**
- Create: `skills/aimaster/studio/mini_app.py`
- Create: `skills/aimaster/studio/static/mini-app.js`
- Modify: `skills/aimaster/studio/static/index.html`
- Test: `skills/aimaster/scripts/test_mini_app.py`

- [ ] Write failing tests for Telegram `initData` HMAC, stale auth date, owner mismatch, read-only snapshot and safe action forwarding.
- [ ] Implement loopback gateway serving the existing dashboard shell and authenticated `/mini-api/*` routes; raw Studio loopback routes remain private.
- [ ] Add Telegram theme/mobile bootstrap and visible connection state without provider or credential exposure.
- [ ] Run focused tests and JS syntax validation.

### Task 5: HTTPS tunnel and Bot menu

**Files:**
- Modify: `skills/aimaster/scripts/creator_studio_telegram.py`
- Test: `skills/aimaster/scripts/test_telegram_transport.py`
- Modify: `skills/aimaster/references/getting-started.md`
- Modify: `skills/aimaster/references/creator-studio.md`
- Modify: `skills/aimaster/SKILL.md`

- [ ] Write failing tests for cloudflared command construction, URL parsing, absent executable and safe `setChatMenuButton` payload.
- [ ] Implement optional `cloudflared tunnel --url` launcher with bounded readiness and a clear local fallback.
- [ ] Configure Telegram menu button only after a verified HTTPS URL exists.
- [ ] Document macOS setup, sleep/offline boundary, token handling and Windows out-of-scope status.

### Task 6: Verification and release

**Files:**
- Modify: `README.md`, `RELEASES.md`, `VERSION`, `skills/aimaster/VERSION`
- Create: `.журналы/release-notes-<version>.md`

- [ ] Run all Python tests, compileall, JS syntax checks, quick validation, staged secret scan and diff check.
- [ ] Run fake Telegram update and Mini App HMAC flows without real token/network.
- [ ] Run critic-review with code, risk, dependencies and skeptic lenses.
- [ ] Commit, tag and publish only after checks pass.
