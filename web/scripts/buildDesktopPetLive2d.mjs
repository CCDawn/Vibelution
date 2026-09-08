// Run only with an already accepted, official CubismSdkForWeb-5-r.5 SDK.
// This rebuilds the bounded vendored runtime; normal app builds use its output.
import { build } from "vite";
import ts from "typescript";
import { copyFile, cp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const webRoot=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const sdk=resolve(process.argv[2] || (()=>{throw new Error("Pass the extracted official SDK root");})());
const output=resolve(webRoot,"public/desktop-pet/live2d");
const source=resolve(webRoot,"live2d/runtime.ts");
const coreTypes=(await readdir(resolve(sdk,"Core"))).filter(path=>path.endsWith(".d.ts")).map(path=>resolve(sdk,"Core",path));
const program=ts.createProgram([source,...coreTypes],{
 target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,moduleResolution:ts.ModuleResolutionKind.Bundler,
 noEmit:true,noImplicitAny:true,strictNullChecks:false,skipLibCheck:true,useDefineForClassFields:false,
 baseUrl:webRoot,paths:{"@framework/*":[resolve(sdk,"Framework/src/*")]}
});
const diagnostics=ts.getPreEmitDiagnostics(program);
if(diagnostics.length) throw new Error(ts.formatDiagnosticsWithColorAndContext(diagnostics,{
 getCanonicalFileName:name=>name,getCurrentDirectory:()=>webRoot,getNewLine:()=>"\n"
}));
await mkdir(output,{recursive:true});
await build({
 configFile:false,root:webRoot,publicDir:false,
 resolve:{alias:{"@framework":resolve(sdk,"Framework/src")}},
 esbuild:{tsconfigRaw:{compilerOptions:{useDefineForClassFields:false}}},
 build:{outDir:output,emptyOutDir:false,target:"es2022",minify:true,
  lib:{entry:source,formats:["es"],fileName:()=>"runtime.js"}}
});
await mkdir(resolve(output,"Core"),{recursive:true});
await copyFile(resolve(sdk,"Core/live2dcubismcore.min.js"),resolve(output,"Core/live2dcubismcore.min.js"));
await cp(resolve(sdk,"Framework/Shaders/WebGL"),resolve(output,"Shaders"),{recursive:true});
const modelRoot=resolve(process.argv[3] || (()=>{throw new Error("Pass the authorized XiaoLuo model directory");})());
const model=JSON.parse(await readFile(resolve(modelRoot,"小洛.model3.json"),"utf8"));
const paths=[model.FileReferences.Moc,model.FileReferences.Physics,...model.FileReferences.Textures,...Object.values(model.FileReferences.Motions).flatMap(entries=>entries.map(entry=>entry.File)),"小洛.model3.json"];
for(const path of paths){await mkdir(dirname(resolve(output,"XiaoLuo",path)),{recursive:true});await copyFile(resolve(modelRoot,path),resolve(output,"XiaoLuo",path));}
await copyFile(resolve(sdk,"LICENSE.md"),resolve(output,"LICENSE.md"));
const sha=bytes=>createHash("sha256").update(bytes).digest("hex");
await writeFile(resolve(output,"build-manifest.json"),JSON.stringify({
 sdk:"CubismSdkForWeb-5-r.5",
 sourceSha256:sha(await readFile(source)),
 runtimeSha256:sha(await readFile(resolve(output,"runtime.js"))),
 sourceUrl:"https://cubism.live2d.com/sdk-web/bin/CubismSdkForWeb-5-r.5.zip"
},null,2)+"\n");
