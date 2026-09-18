/**
 * MolHub declares no geometry of its own.
 *
 * The constitution is vendored from molcrafts-ui, and the site archetype's four
 * differences (body copy, three control heights) live in `density-site.css`
 * beside it. Anything this product restates has two homes and one day two
 * values — which is how its controls came to be 40px here and 32px in the
 * shared layer, discoverable only by diffing two files.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "@rstest/core";

const here = dirname(fileURLToPath(import.meta.url));
const read = (name: string): string => readFileSync(resolve(here, name), "utf8");

/** Token names declared in a stylesheet, for the roles the constitution owns. */
const declared = (css: string): Set<string> => {
  const names = new Set<string>();
  const pattern = /^\s*(--(?:spacing|radius|text|font|ease)[a-z0-9-]*)\s*:/gm;
  for (const match of css.matchAll(pattern)) if (match[1]) names.add(match[1]);
  return names;
};

describe("token ownership", () => {
  const shared = new Set([
    ...declared(read("constitution-theme.css")),
    ...declared(read("density-site.css")),
  ]);

  it.each(["tailwind.css", "tokens.css"])("%s restates no shared role", (file) => {
    expect([...declared(read(file))].filter((name) => shared.has(name)).sort()).toEqual([]);
  });

  it("layers the site density after the constitution it overrides", () => {
    const entry = read("tailwind.css");
    const constitution = entry.indexOf('@import "./constitution-theme.css"');
    const density = entry.indexOf('@import "./density-site.css"');
    expect(constitution).toBeGreaterThan(-1);
    expect(density).toBeGreaterThan(constitution);
  });

  it("keeps the site density to differences that name a reading situation", () => {
    // Four roles. A fifth wants a sentence about how a site is read, not a
    // preference — otherwise it is drift wearing an archetype's name.
    expect([...declared(read("density-site.css"))].sort()).toEqual([
      "--spacing-control",
      "--spacing-control-comfortable",
      "--spacing-control-compact",
      "--text-body",
    ]);
  });
});
