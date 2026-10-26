import {mkdtempSync,writeFileSync,mkdirSync,rmSync,linkSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {afterEach,describe,it,expect,vi} from "vitest";
import {AssistantThemeControl} from "../src/assistant/assistantThemeControl.js";
import {LAUNCHER_ASSISTANT_URL} from "../src/assistant/assistantBridge.js";
import {createAssistantAppearanceMainControl} from "../src/assistant/appearanceMainControl.js";
const roots:string[]=[];afterEach(()=>{for(const r of roots.splice(0))rmSync(r,{recursive:true,force:true});});
const req={deliveryId:"a".repeat(32),action:"operator_image_upload" as const,operation:"import" as const,kind:"avatar" as const,timeoutMs:120000};
function setup(){const root=mkdtempSync(join(tmpdir(),"assistant-import-"));roots.push(root);const file=join(root,"user.png");writeFileSync(file,Buffer.from("89504e470d0a1a0a","hex"));const upload=vi.fn(async()=>({ok:true,status:"applied",verified:true,kind:"avatar",selection:"workspace/user_avatars/native.png"}));return {root,file,upload};}
describe("operator-chosen image to private canonical owner",()=>{
 it("projects a real parsed theme intent into the strict renderer owner",async()=>{
  const theme=new AssistantThemeControl();const frame={url:LAUNCHER_ASSISTANT_URL};
  const contents={mainFrame:frame,isDestroyed:()=>false,send:(_channel:string,payload:unknown)=>{const p=payload as Record<string,unknown>;theme.acceptResult({sender:contents,senderFrame:frame},{...p,code:p.operation==="read"?"read":"applied",theme:p.theme??"light"});}};
  const control=createAssistantAppearanceMainControl({chooseImage:async()=>null,importImage:async()=>({}),theme:input=>theme.request(contents,input)});
  expect(await control({deliveryId:req.deliveryId,action:"launcher_theme_set",operation:"set",theme:"dark"})).toEqual({schemaVersion:1,operation:"set",code:"applied",theme:"dark"});
 });

 it("imports bounded selected bytes without exposing source paths",async()=>{const f=setup();const control=createAssistantAppearanceMainControl({chooseImage:async()=>f.file,importImage:f.upload,theme:async()=>({})});expect(await control(req)).toEqual({schemaVersion:1,operation:"import",kind:"avatar",code:"applied",verified:true,selection:"workspace/user_avatars/native.png"});expect(f.upload).toHaveBeenCalledOnce();expect(f.upload.mock.calls[0]?.[0]).toMatchObject({kind:"avatar",filename:"user.png",contentType:"image/png",dataBase64:"iVBORw0KGgo="});});
 it("does not write on cancel, abort, oversized or linked selections",async()=>{const f=setup();const abort=new AbortController();abort.abort();const control=createAssistantAppearanceMainControl({chooseImage:async()=>f.file,importImage:f.upload,theme:async()=>({})});expect(await control(req,abort.signal)).toMatchObject({code:"unavailable"});const cancel=createAssistantAppearanceMainControl({chooseImage:async()=>null,importImage:f.upload,theme:async()=>({})});expect(await cancel(req)).toMatchObject({code:"cancelled"});linkSync(f.file,join(f.root,"link.png"));expect(await control(req)).toMatchObject({code:"invalid_image"});expect(f.upload).not.toHaveBeenCalled();});
 it("forgets an aborted waiter but never writes after a late file choice",async()=>{const f=setup();let release!:(v:string)=>void;const choice=new Promise<string>(r=>release=r);const control=createAssistantAppearanceMainControl({chooseImage:()=>choice,importImage:f.upload,theme:async()=>({})});const abort=new AbortController();const task=control(req,abort.signal);await Promise.resolve();abort.abort();expect(await task).toMatchObject({code:"unavailable"});expect(await control({...req,deliveryId:"b".repeat(32)})).toMatchObject({code:"busy"});release(f.file);await new Promise(r=>setTimeout(r,5));expect(f.upload).not.toHaveBeenCalled();});
 it("does not promote malformed or mismatched host results",async()=>{const f=setup();const control=createAssistantAppearanceMainControl({chooseImage:async()=>f.file,importImage:async()=>({ok:true,status:"applied",verified:true,kind:"background",selection:"C:/secret.png"}),theme:async()=>({})});expect(await control(req)).toMatchObject({code:"unknown",verified:false});});
});
