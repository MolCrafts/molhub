# Vendored release candidates

MolHub normally consumes published MolCrafts packages from npm. MolVis 0.2.0
has not been published yet, so the Inspector temporarily consumes the exact npm
package artifacts in this directory.

Both tarballs were built from the clean, pushed MolVis commit
`98eb42525975a2ada46c619d163679b62cc94faf` on `release/v0.2.0`:

- `molcrafts-molvis-core-0.2.0.tgz`
- `molcrafts-molvis-stage-0.2.0.tgz`

They preserve the package names and public exports used by production code. No
MolVis source is copied into MolHub. Replace the two `file:` dependencies in
`apps/web/package.json` with `0.2.0` after the packages are published.

Reproduction:

```sh
git clone https://github.com/Roy-Kid/molvis.git
cd molvis
git checkout 98eb42525975a2ada46c619d163679b62cc94faf
npm ci
npm run build --workspace @molcrafts/molvis-stage
npm pack --workspace @molcrafts/molvis-core
npm pack --workspace @molcrafts/molvis-stage
```
