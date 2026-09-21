# Telegram transport for macOS

## Goal

Let a macOS user continue the same AI Мастерская projects from Telegram while
the Mac is running, without copying project state or moving provider logic into
Telegram.

## Scope

- macOS only in this release; Windows and native Windows installation are out of
  scope.
- Existing Creator Studio workspace/state/ledger remain the source of truth.
- Telegram Bot API is an additional transport, not a second project engine.
- Owner-only private chat; pairing is local and never exposes the bot token in
  chat, logs, URLs or public state.
- Existing deterministic commands/questions continue to work.
- Text Telegram messages enter a durable local inbox and are processed by a
  local Codex CLI bridge when available; no provider call is made by the bot
  itself.
- The Mini App is the existing dashboard shell served through a local gateway.
  It reads the same project APIs and can create only existing safe chat/decision
  requests; it never receives provider credentials.
- A Cloudflare Quick Tunnel is optional and started locally only to provide the
  HTTPS URL Telegram requires. The Mac must remain awake and the tunnel URL is
  refreshed on restart.

## Non-goals

- Cloud persistence, always-on operation while the Mac is off, multi-user access,
  public sharing, Windows support, or a new provider orchestration layer.
- Voice/photo/video/document intake and callback keyboards are a later stage; the
  first release uses text commands and the Mini App project navigation.
- Accepting a raw token in a Codex message or storing it in project state.

## User flow

1. Run `python3 scripts/creator_studio_telegram.py setup` locally.
2. Enter the BotFather token in a hidden terminal prompt; send the locally shown
   `/start <pairing-code>` to pair.
3. Run `python3 scripts/creator_studio_telegram.py run --workspace WS`.
4. Telegram shows the Mini App button. `/open PROJECT` selects the same project;
   text is queued for the local agent bridge.
5. The bridge launches one Codex CLI job per message with the selected project
   and exact workspace path; results are delivered to the same Telegram chat.

## Security invariants

- Telegram updates are accepted only from the paired owner and private chat.
- Mini App API validates Telegram `initData` HMAC and freshness before reading
  project data or creating a request.
- Bot token lives in macOS Keychain when available, with a mode-0600 file fallback
  for test environments; it is never part of a URL or subprocess argv.
- Tunnel exposes only the authenticated Mini App gateway, not raw loopback
  Studio endpoints.
- Every bridge request has an idempotency key and a bounded output/timeout.
