# MolHub UI primitives

Shared MolCrafts components come from **molcrafts-ui** via:

```bash
cd ~/work/molcrafts/molcrafts-ui && npm run sync:products
```

| File | Source | Notes |
|------|--------|-------|
| `button.tsx` | registry | Shared control button |
| `code.tsx` | registry | inline/block + wrap |
| `empty-state.tsx` | registry | density variants |
| `tooltip.tsx` | registry | Radix tooltip |
| `utils` (`@/lib/utils`) | registry | constitution-aware `cn` |
| `badge.tsx` | **product** | `BadgeTone` registry vocabulary (not job status) |
| `input.tsx` | **product** | search-field density |
| `tabs.tsx` | **product** | line-default registry chrome |

`components.json` registers `@molcrafts` → `molcrafts-ui/public/r/{name}.json`.
