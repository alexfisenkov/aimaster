# Provider originals and GET-only recovery

Paid generation and local collection are separate. The host returns a structured completed-provider
GET receipt; the normal parent Operator saves it privately and collects the exact original.
No Chrome or child sandbox/network permission changes are needed. A timeout or post-call setup
error stays protected as `outcome_unknown`; the generation is never silently replayed.

Immediately after a provider returns a queued creation/request ID, before long polling, the host
runs `creator_studio_operator.py record-ack WS ACTION --file PRIVATE_ACK.json`. Its exact fields
are provider, model, operation, creation_id, prompt_sha256, basis_sha256 and
`observation: acknowledged`. The immutable frozen dispatch basis and reserved grant are checked;
the ID survives timeout and orphan recovery. Do not invent the not-yet-known output URL or size.

`creator_studio_operator.py record-provider WS ACTION --file PRIVATE_RECEIPT.json` records an
explicit read-only provider observation. The receipt includes provider/model/operation, creation ID,
prompt/basis SHA, and original artifact ID/URL/MIME/dimensions/duration; upstream size/SHA may be
null. The runtime stores computed collection integrity separately. Do not put signed URLs in chat,
argv, public logs or project content. Keep the receipt file private and outside the installed skill.

`creator_studio_operator.py reconcile WS ACTION` performs only an approved-original GET and local
read-back. For an original already collected through provider GET, `--original-file FILE` requires
its observed SHA in the receipt and uses the same validation/authoring path. An updated signed
URL may be supplied with `record-provider` again: only the same creation/artifact/frozen input facts
and the exact same origin/path are accepted; renewals are separate immutable records. A changed
object path needs explicit provenance review, not an arbitrary proxy redirect.

Owner-authenticated `GET /api/actions/ACTION/collection` reports the safe collection state;
`POST /api/actions/ACTION/collection` with `{}` retries collection from the recorded receipt only.
It accepts no browser URL, path or header. Missing/expired access is a collection blocker, never
authorization for another paid call. The original failure remains in action history. Repeating a
completed reconciliation does not append a second creative result or consume another grant.

Recovery checks the frozen prompt/reference/guide basis. Updating a packaged guide does not rewrite
the old generation's SHA. A changed current target or input basis keeps the verified original and
reports conflict; it is not silently attached to a different creative request.

Collection origins are deliberately exact and provider-bound; no CDN wildcards, custom auth,
redirects, private-address connections or caller-controlled destinations are accepted. Mixed
system DNS answers are filtered; only a checked public numeric address is pinned to the TLS
connection, with hostname verification. No public answer means a refusal before payment. See the
selected route's collection capability before authorizing payment. Installed/configured/authorized
provider states remain distinct from original collection support.

The initial exact origins are Magnific `https://pikaso.cdnpk.net/private/`, SYNTX
`https://r2.syntx.ai` for its owner-artifact URL/identity evidence, and fal
`https://v3.fal.media` / `https://v3b.fal.media` for the selected File result.
SYNTX's generic result can have a null download URL; a resource link alone does not prove an original.
These boundaries follow the [SYNTX observer](https://github.com/alexfisenkov/syntx-mcp/blob/main/src/adapter/syntx/owned-image-artifact-observer.ts)
and [fal CDN](https://fal.ai/docs/documentation/model-apis/fal-cdn); actual account access is separate.
Higgsfield hosted OAuth MCP has no established parent-download origin in this package. Its separate
organization Content API is not silently substituted. Prompt-only tasks remain available.

If an already available host file capability can collect the exact original within its current
permissions, chat may explicitly select `route-set ... --collection-mode host-local-original`.
That host returns `artifact.url: null` and a workspace-relative `artifact.local_path: media/...`
with the same provider-original metadata. The parent validates and registers that file. The browser
cannot select this mode; it grants no new file/network/browser access. Upstream checksum/size stay
null if absent; observed file integrity is stored separately by the collector.
