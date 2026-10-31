# La Fabrique XR — Meta VR Start Developer Competition 2026

What was added for the competition (Productivity track, Adapted division).
La Fabrique existed before the entry period (September 24, 2026); everything
listed here was built during it, in `xr/` and its workflow, and is new.

## 2026-10-31

- **`xr/`: La Fabrique XR on the Immersive Web SDK.** A seated,
  hands-first WebXR app (IWSDK 1.0.1) that opens in mixed reality
  (`immersive-ar`, passthrough) with hand tracking. Its first panel sits
  within a seated reach (`src/layout.ts`: every panel on an arc at 50 cm,
  below eye level, tested to stay inside 60 cm) and answers a pinch or a
  poke.
- **IWSDK's Quest 3 emulator on the published page**, so the experience can be
  tried in a desktop browser without a headset; the Quest browser skips it
  and runs real WebXR.
- **GitHub Pages deployment** (`.github/workflows/xr-pages.yml`): every push
  that touches `xr/` runs its tests, builds it and publishes it.
