# Model selection from a connected route

Run this process separately for every new generation task: image creation,
image editing, image-to-video, text/video generation, motion transfer, video
editing/extension, audio and assembly. A provider choice is not a model choice.

## Build the compatible set first

1. Read the current project's exact target, approved creative inputs and
   intended output. List hard requirements before querying models. For images:
   creation vs edit, character/product/location/style references, their count,
   aspect ratio, resolution and identity/text requirements. For video: duration,
   aspect/resolution, image/video/audio references, character consistency,
   first/last frames, one-shot/per-scene, native audio, motion transfer,
   edit/extend and output constraints.
2. Query the verified route's **full current catalog/schema**, not only its
   recommended or default subset. Do not reuse an earlier session's catalog as
   proof. A saved provider preference only selects which catalog to inspect.
3. Check every candidate against the actual input schema and constraints.
   Exclude a model when any hard requirement is unsupported. Brand family,
   newer version number, price or popularity are never proof of compatibility.
   In particular, never offer a model for character/image/video references
   when its current schema says references are unsupported.
   Map Studio semantics to provider fields only when the live adapter schema
   confirms it (for example, a location image may need provider type `image`,
   not a nonexistent `location` field). Record that mapping.
4. When a capability has several modes or endpoints, treat them as separate
   candidates. Motion control, source-video editing, last-frame continuation
   and generic video reference are different jobs.
5. Do not present private/beta/catalog-only entries as normally available
   unless the current account/session and route explicitly expose them. Use
   provider recommendation metadata only as a ranking signal after compatibility,
   never as the filter that defines the shortlist.

## Present a useful choice

When enough compatible models exist, show a balanced shortlist of roughly
four to six genuinely compatible options: strongest quality, best identity or
reference handling, fastest, economical and another materially different
route when available. If fewer qualify, show all that qualify. Include:

- model name and relevant mode;
- why it fits this exact task;
- meaningful limitation or trade-off;
- observed duration/resolution/reference boundary;
- price only after a current supported cost preview.

In `guided`, always include **“Показать все совместимые модели”** and
**“Выбрать за меня”**. “Choose for me” selects from the compatible set and
records the reason; it does not bypass the model-specific writing-guide choice
or paid-action approval.

In `autopilot`, do not present the list. Use the model named in the idea when
it is in the compatible set; otherwise apply “Выбрать за меня” yourself, weighing
the number of image references and whether video references are used
([video inputs](video-inputs.md)). The writing-guide gate and spending then
follow [autopilot](autopilot.md).
Do not overwhelm the user with incompatible catalog entries. If a well-known
or previously mentioned model was excluded, briefly say why—for example,
“Kling 2.5 не показан: текущий маршрут не принимает character references.”
If the user explicitly narrows the request to one family (for example Nano
Banana), show all compatible variants in that family; do not re-expand to the
whole catalog unless asked.

If no model satisfies all hard requirements, explain the exact conflict and
offer concrete changes (shorter duration, different reference strategy,
per-scene generation, another provider). In `autopilot`, apply the smallest
such change yourself (or the next verified route), record it and list it in
the final report. Never silently drop a reference, shorten the output, lower
resolution or switch providers.

Sound settings require the same schema check. “No music” or “sound effects
off” does not prove that the returned file has no audio stream. When a silent
container is a hard requirement and the model cannot guarantee it, disclose
that and include a verified mute/remux step after generation.

After the choice (the user's, or yours in `autopilot`), record provider, model/mode, observed schema facts and
selection reason in the private operation record. Re-run selection when the
target, required references, model, provider or material constraints change.
