/**
 * The guide for the first moves: an arrow that bobs over where the next
 * move is made, a ring around it, and one line saying what to do. It turns
 * to face the person and disappears once they have decided once.
 */

import { UIKit, UIKitDocument } from '@iwsdk/core';
import { AdditiveBlending, ConeGeometry, Group, Mesh, MeshBasicMaterial, TorusGeometry, Vector3 } from 'three';

import { COLORS, panel, text } from './kit';

export interface Guide {
  group: Group;
  /** Point at `target` (world space) with `line`, or hide when undefined. */
  update(target: Vector3 | undefined, line: string, head: Vector3, time: number): void;
}

export function guide(): Guide {
  const group = new Group();
  const glow = (opacity: number) =>
    new MeshBasicMaterial({ color: 0xff6a45, transparent: true, opacity, blending: AdditiveBlending, depthWrite: false });
  // The arrow points down at the target.
  const arrow = new Mesh(new ConeGeometry(0.012, 0.03, 16), glow(0.95));
  arrow.rotation.x = Math.PI;
  const ring = new Mesh(new TorusGeometry(0.035, 0.0025, 8, 40), glow(0.8));
  const card = panel(0.2, undefined, 'bottom');
  card.setProperties({ padding: 1, backgroundColor: COLORS.accent, borderColor: COLORS.accent });
  const caption = text('', 1.5, COLORS.panel, true);
  card.add(caption);
  const doc = new UIKitDocument(card as UIKit.Container);
  // The card faces the person; the arrow and ring sit under it.
  const facing = new Group();
  facing.add(doc, ring);
  group.add(arrow, facing);
  group.visible = false;
  let shown = '';
  const toward = new Vector3();
  return {
    group,
    update(target, line, head, time) {
      group.visible = !!target;
      if (!target) return;
      if (line !== shown) {
        caption.setProperties({ text: line });
        shown = line;
      }
      // A few centimeters toward the person, so it is never inside a panel.
      group.position.copy(target).addScaledVector(toward.subVectors(head, target).normalize(), 0.06);
      const bob = 0.012 * (1 + Math.sin(time * 4));
      arrow.position.set(0, 0.045 + bob, 0);
      doc.position.set(0, 0.075, 0);
      facing.lookAt(head);
      // The ring lies in the plane facing the person, around the target.
      ring.scale.setScalar(1 + 0.12 * Math.sin(time * 4));
    },
  };
}
