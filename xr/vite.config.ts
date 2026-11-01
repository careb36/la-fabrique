import { iwsdkDev } from '@iwsdk/vite-plugin-dev';
import { defineConfig } from 'vitest/config';

// GitHub Pages serves the app under /<repo>/; XR_BASE sets it in CI, and a
// local build or `vite preview` uses relative paths.
const base = process.env.XR_BASE ?? './';

export default defineConfig({
  base,
  plugins: [
    iwsdkDev({
      emulator: {
        device: 'metaQuest3',
        // A synthetic office: the emulated passthrough shows a real-looking
        // room, and its desk and walls are detected like a real room's.
        environment: 'office_small',
        // Judges without a headset get the emulator on the published page too;
        // the Quest browser is skipped by its user agent and runs real WebXR.
        activation: 'always',
        injectOnBuild: true,
      },
      // The panels are built in code, not UIKitML, so the plugin cannot see
      // which font they use; uikit's default family is kept explicitly.
      bundle: { fonts: ['inter'] },
    }),
  ],
  build: {
    outDir: 'dist',
    target: 'esnext',
  },
  // The voice recognizer's worker imports transformers.js, which loads its
  // ONNX backend on demand: an ES module worker can.
  worker: { format: 'es' },
  esbuild: { target: 'esnext' },
  optimizeDeps: {
    exclude: ['@babylonjs/havok'],
    esbuildOptions: { target: 'esnext' },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
