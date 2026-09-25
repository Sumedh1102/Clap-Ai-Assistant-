# ThreeUI Predictive Arc — source verification

CLAP's central visual is the registered ThreeUI component **`PredictiveArcCanvas`**
(`@designcodeio/threeui`, variant `predictive`), used unmodified with:

```tsx
<PredictiveArcCanvas mode="dark" speed={1.00} hue={0} saturation={1.00} brightness={1.00} />
```

This file records how the source was obtained and verified (2026-09-25).

## 1. How the source was obtained

The registry endpoint `https://threeui.com/source-code/predictive-arc.json` could **not**
be fetched from the build environment: its network policy refused the connection to
`threeui.com` (egress proxy `CONNECT` 403). No approximation was written instead. The
registered source was obtained from the component's upstream repository and the
published package, and verified against the SHA-256 hashes of the registration:

| Source | Identity |
|---|---|
| npm package | `@designcodeio/threeui@1.2.0` (maintainer `mengto`, homepage threeui.com) |
| Tarball SHA-512 | `sha512-E6F/+IPfLKYatB5W62H3gK1bp9WYvfO6xuWBaBh8oLVR7fbTeeEwgLqqy7ZPMA0zmDpAy03nKYOIswBXsstL2g==` |
| npm provenance (SLSA v1, Sigstore) | built by `.github/workflows/publish-npm.yml` in `github.com/MengTo/threeui`, commit `68802d5428071ada5c20db8094b1649e6bb770ed` |
| Upstream repository | `github.com/MengTo/threeui` at that same commit |
| Registration in that repo | `src/data/shaders.tsx` entry `"id": "predictive-arc"`, `"sourceCommit": "SHA-256 fa86582fc870"`, `"importName": "PredictiveArcCanvas"`, `"runtime": "Canvas 2D + Raw WebGL + Three.js r128"` |

The tarball's SHA-512 equals the attested digest, and it equals the `integrity` recorded
for the package in this project's `package-lock.json`. The installed `lib-dist/` is
byte-identical to that tarball.

## 2. Registered file hashes

SHA-256 of each registered file at commit `68802d5`, compared with the registration's
published hashes:

| File | Registered SHA-256 | Result |
|---|---|---|
| `src/shaders/predictive-arc/PredictiveArcCollection.tsx` | `b77a845ab2fa8e8ef8d9b6812d71efe6f320d865d97ec97b2e15253b5950fd63` | ✅ match |
| `src/shaders/predictive-arc/PredictiveArcCanvas.tsx` | `ebaa5a1b1f785c7772aaedc2b195318fd63bd9c3e5e5d8e175600968b245dae7` | ✅ match |
| `src/shaders/predictive-arc/predictiveArcRenderer.ts` | `fc08c66b13c4a8173c8a88845926b72266d1b1a4fc345c84f44ee61fbfaba92b` | ✅ match |
| `src/shaders/data-pixel-arc/DataPixelArcCanvas.tsx` | `2e25156d43dfd1bf0fb47384f75df240cd0c4038deae75a8dacae7c213269c5b` | ✅ match |
| `src/shaders/data-pixel-arc/dataPixelArcRenderer.ts` | `65bdfb98424996d935923f39f163e1667f0bc2b8faa458d900f4450beabba0eb` | ✅ match |
| `src/shaders/neuform-isolated/NeuformBatchEffects.tsx` | `dc68c51bea26b922965de44b4fb8d6c432607508fb2b61e16ed60d245da1a69f` | ✅ match |
| `src/shaders/neuform-isolated/sources/amber-halftone.html` | `3d9ebb64a15a1985c4cef1f01457281a49b2d9900405fd674e8748cac8af00a0` | ✅ match |
| `src/shaders/neuform-isolated/sources/signal-particles.html` | `613a2005d18795dbc25a5d0f93c3ae4dfecdfcb939ea6e2c5702b82eb1e4bfff` | ✅ match |
| `src/shaders/neuform-isolated/sources/override-grid.html` | `dc7800f2b6b6329b8b71ea4a06b82af91cff8379701c6a7fa4c9a92d47f89d6c` | ✅ match |
| `src/shaders/ribbon-field/RibbonFieldBackground.tsx` | `fab02cb57c44c7307afd29cd03d01141372ad90163632b9a6a77910a245a5996` | ✅ match |
| `src/shaders/ribbon-field/ribbonFieldShaders.ts` | `ab578acab44bbff7f3cf67f1c82b3e2e1d03689de3fcbdc23681e8b5a0a3536c` | ✅ match |
| `src/shaders/neuform-isolated/NeuformIsolatedEffects.tsx` | `fe9856234253bc3c1a13b3afb84f3d84644dfa6d578e7203bb3e1dd5eced1b75` | ⚠️ differs (community copy: `dfdb68e7957ebe7fb4e59f07ad54cd7bba7047a424fc14ab026211b6c2a58402`); no commit in the repo's history matches |
| `src/shaders/neuform-isolated/sources/void-protocol.html` | `affd21553ba951c0ff0f5a8e40a84ae70d49aaff3c4c69ea4ae1ec897dec21e3` | ✅ match |
| `src/shaders/neuform-isolated/NeuformCraftEffects.tsx` | `0a1680c3c119dba8c61d946322afa0b64d36dfd80956fb5e7c3fd017d7bfa450` | ✅ match |
| `src/shaders/neuform-isolated/sources/nexus-unified-flow.html` | `fa1a015ae407dc2091c3c96239d28107e973cbc03aa7abef37dd5da791d5428b` | ✅ match |
| `src/shaders/threeui.css` | `efe4447139f1358dd8e9be68edf6fa46cbefbd1de423a4d6c439ca61d2c8eccf` | ⚠️ not present — the community repo ships these selectors as `src/shaders/community.css`; the package ships them as `style.css` |

**All three Predictive Arc files match exactly.** The two exceptions are not on the
`predictive` variant's code path:

- `NeuformIsolatedEffects` is only lazy-loaded for the `void-field` variant.
- The only rules the Predictive Arc uses are `.threeui-background` (sizing and dark
  background), `.threeui-background > canvas` (absolute fill) and
  `.predictive-arc--light`. They are identical in `community.css` and the packaged
  `style.css`, which is exactly what the configured usage imports
  (`@designcodeio/threeui/style.css`).

To re-check against the registry itself, from a network that can reach threeui.com:

```bash
curl -sO https://threeui.com/source-code/predictive-arc.json
```

## 3. What the `predictive` variant actually runs

- `PredictiveArcCanvas` → `PredictiveArcCollection` → `PredictiveArcCanvas` (core) →
  `predictiveArcRenderer.ts`: a **Canvas 2D** pixel-arch renderer (`getContext("2d")`),
  with `ResizeObserver` sizing, device-pixel ratio capped at 2, and a
  `requestAnimationFrame` loop paused by `IntersectionObserver` and `visibilitychange`.
  Everything is cleaned up on unmount.
- "Raw WebGL + Three.js r128" in the registration covers the family's **other**
  variants (`ribbon-field` is raw WebGL; `amber-halftone` loads Three.js r128 inside
  its iframe source). Those are separate lazy chunks that are never fetched for `predictive`.
- Three.js r128 is provided by the package's own pinned dependency
  `three128 → three@0.128.0`, unchanged. `three@0.149.0` (the lowest version the package
  supports, and the one it is built against) is pinned only because the package declares
  `three` as a peer and npm would otherwise install the newest one. No Three.js code is
  included in the CLAP HUD bundle.

## 4. How CLAP uses it

- `web/frontend/src/components/ClapCore/ClapCore.tsx` imports
  `{ PredictiveArcCanvas } from "@designcodeio/threeui"` and
  `"@designcodeio/threeui/style.css"`, then renders it inside `.shader-frame`.
- `vite.config.ts` resolves that exact import to the package's own documented
  per-component entry, `@designcodeio/threeui/components/PredictiveArcCanvas`, which
  re-exports the same `shaders/predictive-arc/PredictiveArcCollection.js`. This keeps
  the other ~80 library components, and their Three.js copies, out of the dev
  pre-bundle.
- No renderer, shader or CSS file from the package is copied, edited or re-implemented.
  In STANDBY the props are exactly `mode="dark" speed={1.00} hue={0}
  saturation={1.00} brightness={1.00}`. For other assistant states, `speed`,
  `brightness` and `saturation` change through the component's own public props,
  which the renderer reads every frame (see `ARC_RESPONSE` in `ClapCore.tsx`; set
  `reactive={false}` to keep the base values in every state).

## 5. Runtime checks performed (headless Chromium)

- One canvas inside `.threeui-background.predictive-arc.predictive-arc--dark`
  (`data-mode="dark"`), canvas `filter: hue-rotate(0deg) saturate(1)`, and the
  package's `position:absolute` canvas rule applied.
- The arc core pixels are lit violet, background pixels are the renderer's `#030303`,
  and consecutive frames differ (the arc is animating).
- Backing store = CSS size × min(DPR, 2) at 1440×900@2x, 1920×1080@1x, 2560×1440@2x,
  1280×800@2x, 820×1000@2x, 390×844@3x, and after a live resize. No page scroll at
  any size.
- Production build and Vite dev server (React StrictMode): no page errors, no console
  errors, exactly one arc render loop, and no Three.js loaded.
