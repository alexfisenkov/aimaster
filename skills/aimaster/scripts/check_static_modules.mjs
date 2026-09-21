#!/usr/bin/env node
// Parse every browser module under studio/static as a real ES module.
//
// `node --check file.js` silently passes files that start with `import`
// (Node treats them as ESM and skips the CommonJS syntax check), so a broken
// dashboard module can reach a release with a green `node --check`.
// This script parses each file with vm.SourceTextModule instead: parse only,
// nothing is linked or executed.
//
// Usage: node --experimental-vm-modules --no-warnings check_static_modules.mjs [dir ...]
// Exit 0 — all files parse; 1 — at least one syntax error; 2 — nothing to check.

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const roots = process.argv.length > 2
  ? process.argv.slice(2)
  : [path.resolve(here, "..", "studio", "static")];

let checked = 0;
let failed = 0;

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (/\.(m?js)$/.test(entry.name)) parse(full);
  }
}

function parse(file) {
  checked += 1;
  try {
    new vm.SourceTextModule(fs.readFileSync(file, "utf8"), { identifier: file });
  } catch (error) {
    failed += 1;
    console.log(`FAIL ${file}: ${error.message}`);
  }
}

for (const root of roots) {
  if (!fs.existsSync(root)) {
    console.log(`missing directory: ${root}`);
    process.exit(2);
  }
  walk(root);
}

if (checked === 0) {
  console.log("nothing to check");
  process.exit(2);
}
console.log(`${checked} modules parsed, ${failed} failed`);
process.exit(failed ? 1 : 0);
