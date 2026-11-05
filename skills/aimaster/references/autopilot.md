# Fully automatic mode (`autopilot` in project state)

The user approves one short brief containing output type, duration, service/model choice or selection rule, guide rule, supplied/reused references, and montage/materials choice. Show the one-time CLI spending notice when enabling the mode. After brief approval, do not require further questions for ordinary creative choices, stage approvals, variants or paid generations. There is no media-count cap. The approval applies to this project and its chosen route, not unrelated files/accounts or publication.

Before every external call, verify current route/model/schema, guide scope and SHA, reference binding, current stage and prompt basis. `action enqueue WS ID --type generate|vary|regenerate --target T --expected-revision N --idempotency-key K` uses the runtime's automatic scoped grant. Reuse K only to inspect/deduplicate the same intended action; an uncertain paid POST needs provider read-back, never a new call. Take the returned revision after the grant. Collect and register outputs canonically, choose exact versions, then approve stages. A true blocker (auth, missing route, incompatible media, contradictory instructions) becomes a visible status and report. Switching back to guided voids unused automatic grants; do not silently requeue them.

For video/mixed choose montage or materials before brief approval. Materials can finish with a checked manifest and no MP4. Montage starts with the base render, then optional styles/overlays/improvements; keep prior versions. Do not treat AIEditing as a renderer: consult it only to select or build an applicable editing format. Report what media was inspected, exported, listened to, delivered and what remains unverified.

When montage was chosen, read [montage.md](montage.md). Check `montage status`
first. If it reports `engine.state: missing`, run the returned `engine.install`
or `install_argv` free prerequisite command under the approved automatic mode,
then check status again. If it still reports `engine.state: missing`, report
“the montage engine could not be installed” as a blocker. Continue with
`montage draft` and `montage render` only after the engine and selected clips
are ready. The newer `montage build` can make the base version directly; a
failed render never means a completed MP4.

## Allowed stops

Stop for a concrete missing account capability, unsupported collection path, incompatible source,
stale/ambiguous required basis, or an unknown paid outcome. Preserve the action and evidence;
never repeat a paid generation to repair a download. Ordinary choices covered by the approved
brief are not new permission gates. See [provider recovery](provider-recovery.md).

## Tool check before any no

Read the current exposed tool catalog, its selected operation schema, and a read-only capability
probe. A configured connector alone does not prove login or collection. Respect an explicit host
denial; do not change sandbox, browser or network permissions to bypass it. Unsupported parent
collection is diagnosed before payment; prompt-only work can continue.
