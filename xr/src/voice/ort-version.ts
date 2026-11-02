/**
 * The ONNX runtime version this layer depends on, for the places that must
 * load its WASM from a CDN build of exactly that version (a mismatch between
 * the library and its WASM fails at load). A test holds it to package.json.
 */
export const ORT_VERSION = '1.31.0-dev.20260914-8d85527a0';
export const ORT_CDN_BASE = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VERSION}/dist/`;
