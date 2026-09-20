"""Single owner of the status to public Russian message table.

Repair, 2026-09-16 (ticket 09, second attempt, condition 1). Two modules
need the exact same text for the exact same terminal status:

- `adapters.py` chooses it in `validate_public_result`, the only place a
  chat-reported or verifier-reported outcome can become a stored,
  browsable `public_result`.
- `ledger.py` chooses it in `ActionLedger.recover_inflight`, the one place
  that can *override* a decision's own status after the fact (today: when
  a verifier's `external_id` fails validation, the status it reported is
  downgraded to `outcome_unknown`).

Before this module existed the table lived in `adapters.py` alone, so
`ledger.py`'s override had no correct text to reach for and kept whatever
`message` the pre-override `public_result` already carried — a `"Готово."`
surviving a downgrade to `outcome_unknown` untouched. A single source
closes that gap: whichever module needs the text for a status looks it up
here, and neither re-derives nor hardcodes its own copy. The message a
person reads is always chosen by the final, stored status alone — never by
which status something *used to be* before an override.

`STATUS_MESSAGE_RU` is total over `ledger.TERMINAL_STATUSES`: every status
a public result can ever be finished or recovered with has exactly one
fixed Russian sentence.
"""

from __future__ import annotations


STATUS_MESSAGE_RU = {
    "succeeded": "Готово.",
    "failed": "Не удалось выполнить действие.",
    "needs_chat": "Нужно продолжить в чате.",
    "needs_chat_setup": "Нужна настройка маршрута в чате.",
    "outcome_unknown": "Исход нужно проверить в чате.",
}
