/**
 * Small helpers over uikit for the room's panels.
 *
 * uikit lengths inside a panel are centimeters here: a panel is created with
 * its world size in meters (`sizeX`), and its content laid out in units where
 * 100 make a meter, so `fontSize: 2` is text two centimeters tall.
 */

import { UIKit } from '@iwsdk/core';

type ColorName =
  | 'panel'
  | 'border'
  | 'text'
  | 'muted'
  | 'accent'
  | 'accentHover'
  | 'ok'
  | 'warn'
  | 'bad'
  | 'button'
  | 'buttonHover'
  | 'add'
  | 'remove';

/** The palette in use. High contrast swaps it in place (`setContrast`). */
export const COLORS: Record<ColorName, string> = {
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
};

const STANDARD = { ...COLORS };

/**
 * High contrast: pure black panels with white borders and white text, and
 * the state colors at their brightest. The same layout, nothing hidden.
 */
const HIGH_CONTRAST: Partial<Record<ColorName, string>> = {
  panel: '#000000',
  border: '#ffffff',
  text: '#ffffff',
  muted: '#f4f4f5',
  button: '#000000',
  buttonHover: '#3f3f46',
  ok: '#bef264',
  warn: '#fde047',
  bad: '#fca5a5',
};

// What the palette paints, so a change of palette repaints it.
const painted = {
  panels: [] as UIKit.Container[],
  texts: [] as { text: UIKit.Text; color: ColorName }[],
  buttons: [] as { root: UIKit.Container; color?: ColorName }[],
};

const nameOf = (value: string): ColorName | undefined =>
  (Object.keys(COLORS) as ColorName[]).find((k) => COLORS[k] === value);

export let highContrast = false;

/** Switch the palette and repaint every panel, text and button made so far. */
export function setContrast(high: boolean): void {
  highContrast = high;
  Object.assign(COLORS, STANDARD, high ? HIGH_CONTRAST : {});
  for (const p of painted.panels) {
    p.setProperties({ backgroundColor: COLORS.panel, borderColor: COLORS.border, borderWidth: high ? 0.4 : 0.2 });
  }
  for (const { text: t, color } of painted.texts) t.setProperties({ color: COLORS[color] });
  for (const { root, color } of painted.buttons) {
    // A button in a color of its own (Approve's green) keeps it; every
    // button gets a white outline.
    root.setProperties({
      ...(color ? { backgroundColor: COLORS[color] } : {}),
      borderColor: COLORS.border,
      borderWidth: high ? 0.3 : 0,
    });
  }
}

/**
 * A panel's root: `widthM` meters wide, laid out in centimeters. Its height
 * follows its content unless `heightM` fixes it; it hangs from its top edge,
 * or stands on its bottom edge. A panel in colors of its own (the guide's
 * card) passes `repaint: false` so high contrast leaves it alone.
 */
export function panel(
  widthM: number,
  heightM?: number,
  anchorY: 'top' | 'bottom' = 'top',
  repaint = true,
): UIKit.Container {
  const root = new UIKit.Container({
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
    borderWidth: highContrast ? 0.4 : 0.2,
  });
  if (repaint) painted.panels.push(root);
  return root;
}

// Text, rows and buttons never shrink: yoga shrinks children by default,
// which laid lines over each other when a panel's content was tall.
export function text(value: string, size = 1.8, color: string = COLORS.text, bold = false): UIKit.Text {
  const t = new UIKit.Text({
    text: value,
    fontSize: size,
    color,
    fontWeight: bold ? 'bold' : 'normal',
    wordBreak: 'break-word',
    flexShrink: 0,
  });
  const name = nameOf(color);
  if (name) painted.texts.push({ text: t, color: name });
  return t;
}

/**
 * A button big enough to poke with a fingertip: at least four centimeters
 * tall, which is also an easy target for a pinch ray.
 */
export function button(
  label: string,
  onClick: () => void,
  opts: { primary?: boolean; color?: string; grow?: boolean; compact?: boolean } = {},
): { root: UIKit.Container; label: UIKit.Text } {
  const bg = opts.color ?? (opts.primary ? COLORS.accent : COLORS.button);
  const root = new UIKit.Container({
    minHeight: 4.5,
    paddingX: opts.compact ? 0.8 : 2,
    borderRadius: 1.2,
    backgroundColor: bg,
    hover: { backgroundColor: opts.primary ? COLORS.accentHover : COLORS.buttonHover },
    active: { opacity: 0.7 },
    justifyContent: 'center',
    alignItems: 'center',
    flexGrow: opts.grow ? 1 : 0,
    // Grown buttons in a row split it evenly, whatever their labels, and
    // may shrink with it; the others keep their size.
    flexShrink: opts.grow ? 1 : 0,
    ...(opts.grow ? { flexBasis: 0, minWidth: 0 } : {}),
    cursor: 'pointer',
    onClick,
  });
  // Compact buttons share a row; their label is smaller so the longest one
  // ("Next sprint", "Resume") stays inside its half.
  const labelText = text(label, opts.compact ? 1.5 : 1.9, opts.primary ? COLORS.panel : COLORS.text, true);
  root.add(labelText);
  painted.buttons.push({ root, color: opts.color ? undefined : nameOf(bg) });
  return { root, label: labelText };
}

export function row(gap = 1): UIKit.Container {
  return new UIKit.Container({ flexDirection: 'row', gap, alignItems: 'center', flexShrink: 0 });
}
