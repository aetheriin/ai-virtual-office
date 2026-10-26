// Run: npm test   (Node 22+, TypeScript via --experimental-strip-types)
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { avatarFor, mouthAt, pickClip, retargetClips, speechSeconds } from "../lib/avatars.ts";

const clip = (name: string, tracks: THREE.KeyframeTrack[] = []) => new THREE.AnimationClip(name, 1, tracks);
const CLIPS = ["Idle", "Typing", "Talking", "Thinking", "Sitting"].map((n) => clip(n));

function load(file: string): Promise<{ scene: THREE.Group; animations: THREE.AnimationClip[] }> {
  const b = fs.readFileSync(new URL(`../public/avatars/${file}`, import.meta.url));
  return new Promise((res, rej) => new GLTFLoader().parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), "", res as never, rej));
}

test("pickClip maps agent states to clip names", () => {
  assert.equal(pickClip(CLIPS, "typing")?.name, "Typing");
  assert.equal(pickClip(CLIPS, "thinking")?.name, "Thinking");
  assert.equal(pickClip(CLIPS, "standing")?.name, "Talking");
  assert.equal(pickClip(CLIPS, "debating")?.name, "Talking");
  assert.equal(pickClip(CLIPS, "idle")?.name, "Idle");
  assert.equal(pickClip(CLIPS, "idle", { seated: true })?.name, "Sitting");
  assert.equal(pickClip(CLIPS, "debating", { overrides: { debating: "thinking" } })?.name, "Thinking");
  assert.equal(pickClip([clip("mixamo.com")], "typing")?.name, "mixamo.com"); // unnamed Mixamo export
  assert.equal(pickClip([], "idle"), null);
});

test("retargetClips strips the Mixamo prefix and drops position tracks", () => {
  const target = new THREE.Group();
  for (const n of ["Hips", "Spine", "Head"]) target.add(Object.assign(new THREE.Bone(), { name: n }));
  const src = clip("Walk", [
    new THREE.QuaternionKeyframeTrack("mixamorigSpine.quaternion", [0], [0, 0, 0, 1]),
    new THREE.QuaternionKeyframeTrack("mixamorig:Head.quaternion", [0], [0, 0, 0, 1]),
    new THREE.VectorKeyframeTrack("mixamorigHips.position", [0], [0, 100, 0]),
    new THREE.QuaternionKeyframeTrack("mixamorigLeftToeBase.quaternion", [0], [0, 0, 0, 1]),
  ]);
  const [out] = retargetClips([src], target);
  assert.deepEqual(out.tracks.map((t) => t.name), ["Spine.quaternion", "Head.quaternion"]);
  const [withRoot] = retargetClips([src], target, true);
  assert.ok(withRoot.tracks.some((t) => t.name === "Hips.position"));
});

test("retargetClips keeps the prefix when the target skeleton uses it", () => {
  const target = new THREE.Group();
  target.add(Object.assign(new THREE.Bone(), { name: "mixamorigSpine" }));
  const [out] = retargetClips([clip("x", [new THREE.QuaternionKeyframeTrack("Spine.quaternion", [0], [0, 0, 0, 1])])], target);
  assert.deepEqual(out.tracks.map((t) => t.name), ["mixamorigSpine.quaternion"]);
});

test("sample assets: Mixamo clips bind to the RPM-style avatar", async () => {
  const avatar = await load("sample-bot.glb");
  const anims = await load("sample-anims.glb");
  const clips = retargetClips(anims.animations, avatar.scene);
  assert.deepEqual(clips.map((c) => c.name), ["Idle", "Typing", "Talking", "Thinking", "Sitting"]);
  assert.ok(clips.every((c) => c.tracks.length > 0));

  // play "Typing" and check the arm actually rotates forward
  const arm = avatar.scene.getObjectByName("LeftArm")!;
  const mixer = new THREE.AnimationMixer(avatar.scene);
  mixer.clipAction(clips.find((c) => c.name === "Typing")!).play();
  mixer.update(0.1);
  const forward = new THREE.Vector3(0, -1, 0).applyQuaternion(arm.quaternion);
  assert.ok(forward.z > 0.8, `arm should point forward, got z=${forward.z.toFixed(2)}`);

  let face: THREE.Mesh | undefined;
  avatar.scene.traverse((o) => { if ((o as THREE.Mesh).morphTargetDictionary?.mouthOpen !== undefined) face = o as THREE.Mesh; });
  assert.ok(face, "mouthOpen morph target present");
});

test("mouthAt drives a text-based lip-sync", () => {
  assert.deepEqual(mouthAt("ba", 0), { open: 0.25, vowel: null });
  assert.deepEqual(mouthAt("ba", 1 / 14), { open: 1, vowel: "a" });
  assert.equal(mouthAt("a b", 1 / 14).open, 0); // space closes the mouth
  assert.equal(mouthAt("abc", 10).open, 0);     // finished speaking
  assert.equal(speechSeconds("x".repeat(1000)), 8);
});

test("avatarFor merges defaults with the agent entry", () => {
  const m = { defaults: { animations: ["/a.glb"], height: 1.7 }, agents: { pm: { url: "/pm.glb", animations: ["/b.glb"] } } };
  assert.deepEqual(avatarFor(m, "pm")?.animations, ["/a.glb", "/b.glb"]);
  assert.equal(avatarFor(m, "pm")?.height, 1.7);
  assert.equal(avatarFor(m, "fe"), null);
  assert.equal(avatarFor(null, "pm"), null);
});
