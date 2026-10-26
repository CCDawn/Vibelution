import {execFileSync} from "node:child_process";
import {existsSync,mkdirSync,mkdtempSync,readFileSync,readdirSync,realpathSync,rmSync,writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {dirname,join,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {describe,it,expect} from "vitest";
import {AssistantHost} from "../src/assistant/assistantHost.js";
import {AssistantThemeControl} from "../src/assistant/assistantThemeControl.js";
import {LAUNCHER_ASSISTANT_URL} from "../src/assistant/assistantBridge.js";
import {createAssistantAppearanceMainControl} from "../src/assistant/appearanceMainControl.js";
import {CHILD} from "./fixtures/assistantPrivateHost.js";
const PNG="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=";
describe.skipIf(process.platform!=="win32")("actual private appearance import in Temp",()=>{
 it("applies canonical images and recovers them after host restart without a model or project backend",async()=>{
  const root=realpathSync.native(mkdtempSync(join(tmpdir(),"assistant-appearance-native-")));
  const source=resolve(dirname(fileURLToPath(import.meta.url)),"../../..");
  const gitEnv=Object.fromEntries(Object.entries(process.env).filter(([k])=>!k.toUpperCase().startsWith("GIT_")));
  const common=execFileSync("git",["rev-parse","--path-format=absolute","--git-common-dir"],{cwd:source,env:gitEnv,encoding:"utf8",windowsHide:true}).trim();
  const python=join(dirname(common),".venv/Scripts/pythonw.exe");
  const fixture=join(root,"fixture");mkdirSync(join(fixture,"scripts"),{recursive:true});writeFileSync(join(fixture,"scripts/assistant_host.py"),CHILD);
  const config=join(root,"config/config.toml");mkdirSync(dirname(config));writeFileSync(config,readFileSync(join(source,"tests/fixtures/config/llm_schema_v2_provider.toml")));
  const image=join(root,"operator-chosen.png");writeFileSync(image,Buffer.from(PNG,"base64"));
  const env=Object.fromEntries(Object.entries(process.env).filter(([k])=>!k.toUpperCase().startsWith("VIBELUTION_")&&!k.toUpperCase().startsWith("GIT_")&&!k.toUpperCase().includes("API_KEY")));
  for(const [k,leaf] of Object.entries({HOME:"home",USERPROFILE:"home",LOCALAPPDATA:"local",APPDATA:"roaming",TEMP:"temp",TMP:"temp",VIBELUTION_DATA_HOME:"data",VIBELUTION_PROJECTS_HOME:"projects"})){env[k]=join(root,leaf);mkdirSync(env[k],{recursive:true});}
  env.VIBELUTION_CONFIG_PATH=config;env.VIBELUTION_CONFIG_HOME=dirname(config);env.SYNTHETIC_SOURCE_ROOT=source;env.ASSISTANT_TEST_WRITE_ROOT=root;
  let host:AssistantHost|undefined;let cancel=false,theme="light",importCount=0;
  const themeOwner=new AssistantThemeControl(),frame={url:LAUNCHER_ASSISTANT_URL};
  const contents={mainFrame:frame,isDestroyed:()=>false,send:(_channel:string,payload:unknown)=>{const p=payload as {deliveryId:string;operation:"read"|"set";theme?:string};if(p.theme)theme=p.theme;themeOwner.acceptResult({sender:contents,senderFrame:frame},{deliveryId:p.deliveryId,operation:p.operation,code:p.operation==="read"?"read":"applied",theme});}};
  const control=createAssistantAppearanceMainControl({chooseImage:async()=>cancel?null:image,importImage:async(input,key)=>{importCount++;return host!.importOperatorImage(input,key);},theme:(input,signal)=>themeOwner.request(contents,input,signal)});
  const make=()=>new AssistantHost({profileRoot:join(root,"profile"),runtimeRoot:join(root,"runtime"),sourceRoot:fixture,pythonPath:python,env,projects:{},mainControl:(request,signal)=>{
   if(request.action==="launcher_theme_get"||request.action==="launcher_theme_set"||request.action==="operator_image_upload")return control(request,signal);throw new Error("no project control in this fixture");
  },appearanceControl:true});
  let sequence=0;const send=(action:string,parameters:object={})=>host!.request({operation:"send",message:JSON.stringify({action,parameters}),requestId:`synthetic-${++sequence}`});
  try{
   if(!existsSync(python))throw new Error("canonical validation Python missing");
   host=make();await host.start();
   expect(await send("launcher_theme_set",{theme:"dark"})).toMatchObject({code:"applied",theme:"dark"});
   expect(await send("launcher_theme_get")).toMatchObject({code:"read",theme:"dark"});
   const avatar=await send("operator_image_upload",{kind:"avatar"}) as Record<string,unknown>;
   expect(avatar).toMatchObject({code:"applied",kind:"avatar",verified:true,selection:expect.stringMatching(/^workspace\/user_avatars\//)});
   expect(await send("operator_image_options",{kind:"avatar"})).toMatchObject({ok:true,options:[avatar.selection]});
   expect(await host.request({operation:"operatorAsset",kind:"avatar"})).toMatchObject({image:{dataBase64:PNG}});
   expect(await send("operator_image_upload",{kind:"background"})).toMatchObject({code:"applied",kind:"background",verified:true});
   const after=readFileSync(config,"utf8");expect(importCount).toBe(2);
   cancel=true;expect(await send("operator_image_upload",{kind:"avatar"})).toMatchObject({code:"cancelled",verified:false});
   expect(readFileSync(config,"utf8")).toBe(after);expect(importCount).toBe(2);
   await host.stop();host=make();await host.start();
   expect(await host.request({operation:"operatorAsset",kind:"avatar"})).toMatchObject({image:{dataBase64:PNG}});
   expect(await host.request({operation:"operatorAsset",kind:"background"})).toMatchObject({image:{dataBase64:PNG}});
   expect(readdirSync(join(root,"config/avatars"))).toHaveLength(1);
   expect(readdirSync(join(root,"config/theme_backgrounds"))).toHaveLength(1);
  }finally{await host?.stop();rmSync(root,{recursive:true,force:true,maxRetries:10,retryDelay:50});}
 },90000);
});
