/**
 * Small helpers over uikit for the room's panels.
 *
 * uikit lengths inside a panel are centimeters here: a panel is created with
 * its world size in meters (`sizeX`), and its content laid out in units where
 * 100 make a meter, so `fontSize: 2` is text two centimeters tall.
 */

import { UIKit } from '@iwsdk/core';

export const COLORS = {
  panel: '#111317',
  border: '#2a2f37',
  text: '#f4f4f5',
  muted: '#a1a1aa',
  accent: '#ff6a45',
  accentHover: '#ff8a6b',
  ok: '#a3e635',
  warn: '#fbbf24',
  bad: '#f87171',
  button: '#1f242c',
  buttonHover: '#2c333d',
  add: '#86efac',
  remove: '#fca5a5',
} as const;

/**
 * A panel's root: `widthM` meters wide, laid out in centimeters. Its height
 * follows its content unless `heightM` fixes it; it hangs from its top edge,
 * or stands on its bottom edge.
 */
export function panel(widthM: number, heightM?: number, anchorY: 'top' | 'bottom' = 'top'): UIKit.Container {
  return new UIKit.Container({
    sizeX: widthM,
    // Anchored by an edge, so a panel that grows or shrinks with its content
    // never moves into its neighbors.
    anchorY,
    ...(heightM ? { sizeY: heightM } : {}),
    pixelSize: 0.01,
    flexDirection: 'column',
    padding: 2,
    gap: 1.2,
    backgroundColor: COLORS.panel,
    borderRadius: 2,
    borderColor: COLORS.border,
    borderWidth: 0.2,
  });
}

// Text, rows and buttons never shrink: yoga shrinks children by default,
// which laid lines over each other when a panel's content was tall.
export function text(value: string, size = 1.8, color: string = COLORS.text, bold = false): UIKit.Text {
  return new UIKit.Text({
    text: value,
    fontSize: size,
    color,
    fontWeight: bold ? 'bold' : 'normal',
    wordBreak: 'break-word',
    flexShrink: 0,
  });
}

/**
 * A button big enough to poke with a fingertip: at least four centimeters
 * tall, which is also an easy target for a pinch ray.
 */
export function button(
  label: string,
  onClick: () => void,
  opts: { primary?: boolean; color?: string; grow?: boolean } = {},
): { root: UIKit.Container; label: UIKit.Text } {
  const bg = opts.color ?? (opts.primary ? COLORS.accent : COLORS.button);
  const root = new UIKit.Container({
    minHeight: 4.5,
    paddingX: 2,
    borderRadius: 1.2,
    backgroundColor: bg,
    hover: { backgroundColor: opts.primary ? COLORS.accentHover : COLORS.buttonHover },
    active: { opacity: 0.7 },
    justifyContent: 'center',
    alignItems: 'center',
    flexGrow: opts.grow ? 1 : 0,
    flexShrink: 0,
    cursor: 'pointer',
    onClick,
  });
  const labelText = text(label, 1.9, opts.primary ? COLORS.panel : COLORS.text, true);
  root.add(labelText);
  return { root, label: labelText };
}

export function row(gap = 1): UIKit.Container {
  return new UIKit.Container({ flexDirection: 'row', gap, alignItems: 'center', flexShrink: 0 });
}
