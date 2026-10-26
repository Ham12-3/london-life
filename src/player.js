// First-person walker: pointer-lock mouse look, WASD, sprint, collision with walls, fences, trees and water.
import * as THREE from "three";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";

const EYE = 1.68;
const RADIUS = 0.35;
const WALK = 2.2;
const SPRINT = 6.5;
const FLY = 25;

export class Player {
  constructor(camera, dom, collision) {
    this.camera = camera;
    this.collision = collision;
    this.controls = new PointerLockControls(camera, dom);
    this.keys = new Set();
    this.fly = false;
    this.bob = 0;
    camera.position.y = EYE;
    addEventListener("keydown", (e) => {
      if (e.target instanceof HTMLInputElement) return;
      this.keys.add(e.code);
      if (e.code === "KeyN") this.toggleFly();
    });
    addEventListener("keyup", (e) => this.keys.delete(e.code));
    addEventListener("blur", () => this.keys.clear());
  }

  get locked() {
    return this.controls.isLocked;
  }

  toggleFly() {
    this.fly = !this.fly;
    if (!this.fly) this.camera.position.y = EYE;
  }

  teleport(x, z, lookX, lookZ) {
    this.camera.position.set(x, this.fly ? this.camera.position.y : EYE, z);
    if (lookX !== undefined) this.camera.lookAt(lookX, this.camera.position.y, lookZ);
  }

  heading() {
    const d = new THREE.Vector3();
    this.camera.getWorldDirection(d);
    return Math.atan2(d.x, -d.z);
  }

  update(dt) {
    const k = this.keys;
    const fwd = (k.has("KeyW") || k.has("ArrowUp") ? 1 : 0) - (k.has("KeyS") || k.has("ArrowDown") ? 1 : 0);
    const side = (k.has("KeyD") || k.has("ArrowRight") ? 1 : 0) - (k.has("KeyA") || k.has("ArrowLeft") ? 1 : 0);
    const pos = this.camera.position;
    if (this.fly) {
      const up = (k.has("KeyE") || k.has("Space") ? 1 : 0) - (k.has("KeyQ") || k.has("ControlLeft") ? 1 : 0);
      const speed = FLY * (k.has("ShiftLeft") || k.has("ShiftRight") ? 3 : 1) * dt;
      this.controls.moveForward(fwd * speed);
      this.controls.moveRight(side * speed);
      pos.y = Math.max(EYE, pos.y + up * speed);
      return;
    }
    if (!fwd && !side) {
      this.bob *= 0.9;
      pos.y = EYE + Math.sin(this.bob) * 0.02;
      return;
    }
    const sprint = k.has("ShiftLeft") || k.has("ShiftRight");
    const len = Math.hypot(fwd, side);
    const step = (sprint ? SPRINT : WALK) * dt;
    const ox = pos.x, oz = pos.z;
    this.controls.moveForward((fwd / len) * step);
    this.controls.moveRight((side / len) * step);
    let [x, z] = this.collision.resolve(pos.x, pos.z, RADIUS);
    // Water stops you at the bank; try sliding along each axis before giving up.
    if (this.collision.inWater(x, z)) {
      if (!this.collision.inWater(x, oz)) z = oz;
      else if (!this.collision.inWater(ox, z)) x = ox;
      else { x = ox; z = oz; }
    }
    pos.x = x;
    pos.z = z;
    this.bob += dt * (sprint ? 14 : 9);
    pos.y = EYE + Math.sin(this.bob) * (sprint ? 0.06 : 0.035);
  }
}
