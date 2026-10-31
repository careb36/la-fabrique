/**
 * The room as the headset sees it: IWSDK's detected planes and meshes,
 * turned into the plain surfaces `room.ts` lays the factory out on.
 */

import { createSystem, XRMesh, XRPlane } from '@iwsdk/core';
import { Quaternion, Vector3 } from 'three';

import type { Surface } from './room';

/** Labels a bounded mesh carries when it is a work surface. */
const DESK_LABELS = /^(table|desk)$/i;

interface DetectedPlane {
  orientation?: string;
  semanticLabel?: string;
  polygon?: ReadonlyArray<{ x: number; z: number }>;
}

/** Keeps the room's detected surfaces; `room()` reads them when asked. */
export class SurfaceSystem extends createSystem({
  planes: { required: [XRPlane] },
  meshes: { required: [XRMesh] },
}) {
  /** Every surface detected right now, in world coordinates. */
  room(): Surface[] {
    const out: Surface[] = [];
    for (const entity of this.queries.planes.entities) {
      const object = entity.object3D;
      const plane = entity.getValue(XRPlane, '_plane') as DetectedPlane | undefined;
      if (!object || !plane?.polygon?.length) continue;
      object.updateWorldMatrix(true, false);
      const xs = plane.polygon.map((p) => p.x);
      const zs = plane.polygon.map((p) => p.z);
      const [minX, maxX, minZ, maxZ] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
      const center = object.localToWorld(new Vector3((minX + maxX) / 2, 0, (minZ + maxZ) / 2));
      // A plane's normal is its local +y.
      const normal = new Vector3(0, 1, 0).applyQuaternion(object.getWorldQuaternion(new Quaternion()));
      out.push({
        kind: plane.orientation === 'vertical' || Math.abs(normal.y) < 0.5 ? 'vertical' : 'horizontal',
        label: plane.semanticLabel ?? '',
        center: { x: center.x, y: center.y, z: center.z },
        normal: { x: normal.x, y: normal.y, z: normal.z },
        width: maxX - minX,
        depth: maxZ - minZ,
      });
    }
    for (const entity of this.queries.meshes.entities) {
      const object = entity.object3D;
      const label = String(entity.getValue(XRMesh, 'semanticLabel') ?? '');
      if (!object || !entity.getValue(XRMesh, 'isBounded3D') || !DESK_LABELS.test(label)) continue;
      // A table mesh's top: the middle of its bounds, at its highest point.
      const min = entity.getVectorView(XRMesh, 'min');
      const max = entity.getVectorView(XRMesh, 'max');
      object.updateWorldMatrix(true, false);
      const top = object.localToWorld(new Vector3((min[0] + max[0]) / 2, max[1], (min[2] + max[2]) / 2));
      out.push({
        kind: 'horizontal',
        label,
        center: { x: top.x, y: top.y, z: top.z },
        normal: { x: 0, y: 1, z: 0 },
        width: max[0] - min[0],
        depth: max[2] - min[2],
      });
    }
    return out;
  }
}
