# Scoped headless authoring

The standard Claude adapter adds only the exact frozen package directory and denies
package edits. Its per-process shell allowance is one exact command supplied in
`host_authoring.command`, including the current workspace, action ID and request path.
There is no unrestricted Bash/Python allowance and no global configuration change.

For a free authoring job, write one JSON request to the supplied `request_path` and
run that exact command:

```json
{"op":"script.add-version","project_id":"the-job-project","expected_revision":1,
 "data":{"text":"The revised scenario","reason":"Owner requested a revision"}}
```

The gateway accepts only the running job's project and current expected revision.
The request path is fixed inside that workspace; symlinks, traversal, duplicate JSON
keys, unknown operations/fields and external file/catalog arguments are refused.
It calls the existing canonical authoring APIs and returns their real revision/IDs.
For another authorized operation, replace the request JSON and use the returned revision.

Every successful response has `output_ids`: all canonical version IDs actually created by
that operation, including each new storyboard `script_block` version. Accumulate the union
of these lists for the whole job and return it in the host result. A later metadata-only
response with `output_ids: []` must not erase earlier IDs. Asset/reference IDs remain separate
response fields; they do not replace version IDs. The dedicated `assemble` action retains
its existing asset-ID result contract.

Supported operations are script version, initial storyboard, image/motion/audio prompt
version, exact registered guide choice, reference add/attach by workspace asset/library ID,
registration of a file explicitly supplied in the job's attachments, and an explicit uploaded
result. Materials preparation and montage build/export use existing services; export gets a
generated destination inside the workspace. The gateway does not dispatch providers, install
dependencies, alter grants/mode/configuration, delete data or publish anything.

Approval remains an existing owner action: the dashboard's approval control or Telegram
`/stage-approve`. A plain-language approval phrase is not automatically mapped by this gateway.
After that canonical decision, the next prompt-stage operation can proceed; readiness checks
are never bypassed. Guide import/registration and exports to destinations outside the workspace
remain explicit chat/setup operations, not a general file-access allowance.

Paid generate/vary/regenerate jobs cannot use the creative gateway. Their only newly allowed
local command is the exact provider acknowledgement command; completed originals are returned
as provider receipts and attached only by the parent collector. See [provider recovery](provider-recovery.md).

Hosts return `state_sha256: null`; the parent computes the full canonical digest and independently
checks identity, revisions, semantic outputs and preserved history. A supplied legacy hash is
still compared. Host failure records contain bounded reason/exit/parse classifications rather
than raw stdout, signed URLs or tool traces. Reading a file or exiting successfully is not itself
proof that the requested authoring operation was completed.
