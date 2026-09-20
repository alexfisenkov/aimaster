const PROMPT_TAG_PATTERN = /@((?:IMG|VOICE)_\d+)(?![A-Za-z0-9_])/g;
const CANONICAL_TAG_PATTERN = /^(?:IMG|VOICE)_\d+$/;

export function extractTags(text) {
  if (typeof text !== "string") return [];
  const tags = [];
  const seen = new Set();
  for (const match of text.matchAll(PROMPT_TAG_PATTERN)) {
    if (!seen.has(match[1])) {
      seen.add(match[1]);
      tags.push(match[1]);
    }
  }
  return tags;
}

export function missingTags(text, includedTags) {
  const present = new Set(extractTags(text));
  const missing = [];
  const seen = new Set();
  for (const tag of Array.isArray(includedTags) ? includedTags : []) {
    if (!CANONICAL_TAG_PATTERN.test(tag) || present.has(tag) || seen.has(tag)) continue;
    seen.add(tag);
    missing.push(tag);
  }
  return missing;
}

export function appendMissingTags(text, includedTags) {
  const source = typeof text === "string" ? text.trimEnd() : "";
  const suffix = missingTags(source, includedTags).map((tag) => `@${tag}`).join(", ");
  if (!suffix) return source;
  return source ? `${source}, ${suffix}` : suffix;
}

export function tagChipModels(text, tags) {
  const present = new Set(extractTags(text));
  return (Array.isArray(tags) ? tags : [])
    .filter((item) => item && CANONICAL_TAG_PATTERN.test(item.tag))
    .map((item) => ({ ...item, present: present.has(item.tag) }));
}

export function renderTagChips(text, tags) {
  const row = document.createElement("div");
  row.className = "prompt-tag-row";
  const label = document.createElement("span");
  label.className = "prompt-tag-label";
  label.textContent = "Теги стоят по смыслу внутри текста:";
  row.append(label);
  for (const item of tagChipModels(text, tags)) {
    const chip = document.createElement("span");
    chip.className = "prompt-tag-chip";
    chip.dataset.present = String(item.present);
    chip.textContent = [item.tag, item.label].filter(Boolean).join(" · ");
    row.append(chip);
  }
  return row;
}
