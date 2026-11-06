# Provider originals and GET-only recovery

Paid generation and local collection are separate. The host returns a structured completed-provider
GET receipt; the normal parent Operator saves it privately and collects the exact original.
No Chrome or child sandbox/network permission changes are needed. A timeout or post-call setup
error stays protected as `outcome_unknown`; the generation is never silently replayed.

For Magnific, `get-ready-result WS ACTION --file PRIVATE_METADATA.json` accepts a saved completed
GET observation with `status`, the acknowledged `creation_id` (or `id`), and the master
`downloadUrl`, or `mediaCollection.original` (URL or object containing `downloadUrl` or `url`).
It also accepts the Magnific MCP `content` text envelope with top-level `identifier`, `status`
and `downloadUrl`; when the video `mediaCollection` contains an `original` entry, its URL must
match the top-level master URL. A generic preview URL is not a substitute for the master.
For a frozen image position and the observed `text-to-image` response, an explicit `downloadUrl`
or `mediaCollection.original` takes priority. Top-level `url` is used only if no original is
advertised and the response does not mark it as a preview proxy. Preview/thumbnail URLs and
metadata dimensions are not used; image dimensions come from the downloaded bytes.
For video the generic top-level `url` may be a preview. The collector GETs
the selected master, determines MIME and dimensions from its bytes and probes video duration before
writing its private receipt. It does not issue a generation POST. Protect this metadata file as it
may contain a signed URL. QuickTime `qt` originals are retained unchanged as `.mov`; a separately
labelled H.264 MP4 derivative is used for Studio and requires local ffmpeg/ffprobe.

For an erroneous existing receipt, use the explicit correction option with a reason code such as
`preview_dimensions` or `proxy_mistaken_for_original` (lowercase letters, digits and underscores). A
separate immutable correction points back to the old receipt, and the ledger records the change;
the original receipt, prior media and events remain intact. If the creative state has changed,
including a result already attached under the old receipt, collection reports conflict and does not
silently replace it. Review the recovered master and use `resolve-collection WS ACTION --choice adopt
--expected-revision N` to add it as a new result version, or `--choice keep` to retain the current
result. The current revision is required; both decisions are recorded, and repeating a completed
decision does not add another version. If the generation stage is already approved, adopting is
blocked by the normal stage guard. The existing scenario-reopen workflow resets subsequent stage
approvals and may itself be blocked by pending actions; use it only when that broader reset is
intended, or choose keep. A later paid variation still requires its own authorization.

The same explicit decision applies when the first verified receipt conflicts with later project
edits. Adopting requires the original position and prompt/reference route still to match; keeping
requires a current result. An empty position may receive the recovered result through adopt.
Signed-link renewal accepts only a new query for the same provider object.
If an adoption wrote its version but was interrupted before ledger completion, its unique
operation marker lets the dashboard finish the existing operation without adding or selecting
another version, even after a later edit. A fresh keep decision always refers to the current
revision and selection.

When the service supplies only an independently verified export, it remains a separate
`provider_export` representation with private proof, not a confirmed master. Recovery shows that
distinction and keeps it in the new result's caption. The operator-provided service observations
are attestations rather than cryptographic proof of the requested export job.

For this fallback, save the completed creation GET, the status of a ZIP export requested
for that single creation, and its `video_metadata` object privately. Run
`creator_studio_operator.py collect-provider-export WS ACTION --creation-get GET.json --zip-status STATUS.json --zip-job UUID --video-metadata MASTER-FACTS.json`.
The collector checks the archive member against the creation's file and probes the media.
In a controller job return the same evidence in `provider_observation` as specified in the
host result schema. The controller owns collection. A different provider or host-local route
continues to use the applicable provider receipt.

A new paid action cannot succeed through direct child asset/result authoring. Such changes
remain evidence with an unknown outcome and a reserved grant; they are not silently erased or
adopted as parent-collected success. Only a validated completed receipt and parent collection
can promote the paid action. Existing historical terminal records are not rewritten.
For the headless host's free authoring permissions and read-back contract, see
[scoped job authoring](job-authoring.md).

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
