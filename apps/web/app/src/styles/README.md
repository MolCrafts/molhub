# MolHub visual system

The visual system has one source of truth and one framework bridge.

| File | Responsibility |
|---|---|
| `tokens.css` | Reference palette, semantic light/dark tokens, typography, radius, elevation, motion, and MolHub artifact-kind signals |
| `tailwind.css` | Tailwind v4 mapping, base element styles, layout utilities, and accessibility media queries |

## Product position

MolHub is the distribution layer of the MolCrafts ecosystem. It does not host
scientific payloads and it is not a package manager UI: it assigns stable,
versioned coordinates to manifests that point at trusted upstream sources.
The interface therefore prioritizes provenance, resolvability, exact versions,
and copyable machine syntax.

## Token rules

- Components use semantic names such as `background`, `surface`, `border`,
  `foreground`, `accent`, and `signal`; reference colors never appear in page
  components.
- Product taxonomy has exactly three signals: `kind-dataset`, `kind-model`, and
  `kind-plugin`. Lime is reserved for the MolHub publishing/resolution signal.
- Light and dark themes redefine semantic variables in `tokens.css`; component
  markup is theme-independent.
- Coordinates, locators, versions, digests, and filenames use the mono token.
  Display copy uses the display token; controls and prose use the UI token.
- New radii, shadows, timing curves, or spacing constants belong in tokens,
  not one-off component declarations.

## Interaction and accessibility

The theme class lives on `<html>` so portaled Radix content inherits it. The
inline bootstrap in the Start root route applies the stored or preferred theme
before paint. Focus rings, selection, reduced-motion handling, and responsive
page width are defined once in `tailwind.css`.

Every page must remain usable at 320 CSS pixels. Artifact collections use
responsive cards rather than horizontally scrolling desktop tables. Color is
never the only carrier of kind, integrity, or availability.
