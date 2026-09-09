import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
const webRoot=fileURLToPath(new URL("../../../",import.meta.url));
const assets=resolve(webRoot,"public/desktop-pet/live2d");
const hash=(path:string)=>createHash("sha256").update(readFileSync(path)).digest("hex");
describe("bounded XiaoLuo Live2D assets",()=>{
  it("ships the runtime built from the checked-in adapter",()=>{
    const manifest=JSON.parse(readFileSync(resolve(assets,"build-manifest.json"),"utf8"));
    expect(manifest.sdk).toBe("CubismSdkForWeb-5-r.5");
    expect(manifest.sourceSha256).toBe(hash(resolve(webRoot,"live2d/runtime.ts")));
    expect(manifest.runtimeSha256).toBe(hash(resolve(assets,"runtime.js")));
  });
  it("contains every selected asset and excludes voices",()=>{
    const model=JSON.parse(readFileSync(resolve(assets,"XiaoLuo/小洛.model3.json"),"utf8"));
    const refs=model.FileReferences;
    for(const file of [refs.Moc,refs.Physics,...refs.Textures,...Object.values(refs.Motions as Record<string,{File:string}[]>).flatMap(entries=>entries.map(entry=>entry.File))]) {
      expect(existsSync(resolve(assets,"XiaoLuo",file))).toBe(true);
    }
    expect(Object.keys(refs.Motions)).toHaveLength(6);
    expect(JSON.stringify(refs.Motions)).not.toContain('"Sound"');
    expect(existsSync(resolve(assets,"Core/live2dcubismcore.min.js"))).toBe(true);
    expect(existsSync(resolve(assets,"LICENSE.md"))).toBe(true);
  });

  it("ships the pinned Dafeiyu layered rig and its license notices",()=>{
    const whale=resolve(webRoot,"public/desktop-pet/whale-rig");
    for(const file of [
      "index.html",
      "model.psd",
      "eye_close.psd",
      "mouth_close.psd",
      "lib/ag-psd.min.js",
      "lib/genericparts.js",
      "lib/rigger.js",
      "LICENSE",
      "LICENSE-Anime2.5DRig",
      "NOTICE.md",
    ]) {
      expect(existsSync(resolve(whale,file))).toBe(true);
    }
    expect(readFileSync(resolve(whale,"NOTICE.md"),"utf8")).toContain("78d2110b341f3d101cc143f7e0210050a93326ff");
  });
});
