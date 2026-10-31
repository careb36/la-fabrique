import {
  Interactable,
  SessionMode,
  UIKit,
  UIKitDocument,
  VisibilityState,
  World,
} from '@iwsdk/core';

import { arc } from './layout';

/** Seated eye height above the floor. */
const HEAD_Y = 1.2;

const container = document.getElementById('scene-container') as HTMLDivElement;

const world = await World.create(container, {
  xr: {
    // Mixed reality: the room stays visible around the panels.
    sessionMode: SessionMode.ImmersiveAR,
    offer: 'always',
    features: { handTracking: true },
  },
  render: { camera: { position: [0, HEAD_Y, 0] } },
  features: { grabbing: false, locomotion: false, physics: false },
});

const root = new UIKit.Container({
  sizeX: 0.5,
  sizeY: 0.28,
  flexDirection: 'column',
  padding: 3,
  gap: 2,
  backgroundColor: '#111317',
  borderRadius: 3,
  borderColor: '#2a2f37',
  borderWidth: 0.3,
});
root.add(new UIKit.Text({ text: 'La Fabrique XR', fontSize: 5, color: '#f4f4f5', fontWeight: 'bold' }));
const status = new UIKit.Text({
  text: 'A control room for the agents. Pinch or poke the button.',
  fontSize: 2.6,
  color: '#a1a1aa',
});
root.add(status);

const button = new UIKit.Container({
  padding: 2,
  borderRadius: 2,
  backgroundColor: '#ff6a45',
  hover: { backgroundColor: '#ff8a6b' },
  justifyContent: 'center',
  cursor: 'pointer',
  onClick: () => {
    if (world.visibilityState.value === VisibilityState.NonImmersive) {
      world.launchXR();
    } else {
      status.setProperties({ text: 'Hands work: the demo comes in the next step.' });
    }
  },
});
button.add(new UIKit.Text({ text: 'Enter XR', fontSize: 3, color: '#111317', fontWeight: 'bold' }));
root.add(button);

const panel = world.createTransformEntity().addComponent(Interactable);
panel.object3D!.add(new UIKitDocument(root));
// Within a seated reach: at arm's length, a little below eye level.
const [spot] = arc(1);
panel.object3D!.position.set(spot.x, HEAD_Y + spot.y, spot.z);
panel.object3D!.rotation.y = spot.yaw;
