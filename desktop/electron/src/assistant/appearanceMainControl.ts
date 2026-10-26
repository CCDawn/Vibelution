import { constants, type Stats } from "node:fs";
import { lstat, open } from "node:fs/promises";
import { basename, dirname, extname, isAbsolute, resolve } from "node:path";
import { appearanceControlResult, appearanceUnavailable, parseAppearanceClaim, type AppearanceMainControlRequest } from "./appearanceControlProtocol.js";
export type OperatorImageImport = {kind:"avatar"|"background";filename:string;contentType:string;dataBase64:string};
const MIME: Record<string,string> = {".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp"};
async function chain(path:string):Promise<string> {
  const paths:string[]=[];
  for(let next=path;;next=dirname(next)){paths.push(next);if(dirname(next)===next)break;}
  const identities=[];
  for(const part of paths.reverse()){
    const info=await lstat(part);
    if(info.isSymbolicLink() || ((info as Stats & {fileAttributes?:number}).fileAttributes ?? 0)&0x400 || (part!==path && !info.isDirectory()))throw new Error("invalid image");
    identities.push([part,info.dev,info.ino]);
  }
  return JSON.stringify(identities);
}
function stamp(info:Stats):string {
  if(!info.isFile() || info.nlink!==1)throw new Error("invalid image");
  return JSON.stringify([info.dev,info.ino,info.size,info.mtimeMs,info.ctimeMs]);
}
async function chosenImage(path:string,kind:"avatar"|"background",signal?:AbortSignal):Promise<OperatorImageImport>{
  signal?.throwIfAborted();
  if(typeof path!=="string" || !isAbsolute(path) || path.includes("\0"))throw new Error("invalid image");
  const file=resolve(path),type=MIME[extname(file).toLowerCase()];
  if(!type)throw new Error("invalid image");
  const identity=await chain(file),before=await lstat(file),expected=stamp(before),limit=(kind==="avatar"?5:10)*1024*1024;
  if(before.size<1 || before.size>limit)throw new Error("invalid image");
  const handle=await open(file,constants.O_RDONLY|(constants.O_NOFOLLOW??0));
  let bytes:Buffer;
  try{
    if(stamp(await handle.stat())!==expected)throw new Error("image changed");
    const buffer=Buffer.alloc(before.size+1);let size=0;
    while(size<buffer.length){signal?.throwIfAborted();const part=await handle.read(buffer,size,buffer.length-size,null);if(!part.bytesRead)break;size+=part.bytesRead;}
    if(size!==before.size || stamp(await handle.stat())!==expected)throw new Error("image changed");
    bytes=buffer.subarray(0,size);
  }finally{await handle.close();}
  if(await chain(file)!==identity || stamp(await lstat(file))!==expected)throw new Error("image changed");
  signal?.throwIfAborted();
  // The canonical Python image owner validates signature and stores the resource.
  return {kind,filename:basename(file).slice(0,240),contentType:type,dataBase64:bytes.toString("base64")};
}
/** Main-only composition over an operator-selected file and canonical image owner.
 * No paths/URLs from the model, no upload retry, scheduler or durable second state.
 */
export function createAssistantAppearanceMainControl(options:{
  chooseImage:(kind:"avatar"|"background",signal?:AbortSignal)=>Promise<string|null>;
  importImage:(input:OperatorImageImport,deliveryId:string)=>Promise<unknown>;
  theme:(input:{deliveryId:string;operation:"read"|"set";theme?:"dark"|"light"},signal?:AbortSignal)=>Promise<unknown>;
}):(input:AppearanceMainControlRequest,signal?:AbortSignal)=>Promise<Record<string,unknown>>{
  let importing=false;
  return async (input,signal)=>{
    const request=parseAppearanceClaim(input),unavailable=()=>appearanceUnavailable(request);
    if(signal?.aborted)return unavailable();
    if(request.action!=="operator_image_upload"){
      try{return appearanceControlResult(request,await options.theme({deliveryId:request.deliveryId,operation:request.operation,...(request.action === "launcher_theme_set" ? {theme:request.theme} : {})},signal));}catch{return unavailable();}
    }
    const facts=(code:string)=>({schemaVersion:1,operation:"import",kind:request.kind,code,verified:false});
    if(importing)return facts("busy");
    importing=true;
    const work=(async()=>{
      try{
        const selected=await options.chooseImage(request.kind,signal);
        if(signal?.aborted)return unavailable();
        if(selected===null)return facts("cancelled");
        let image:OperatorImageImport;
        try{image=await chosenImage(selected,request.kind,signal);}catch{return signal?.aborted?unavailable():facts("invalid_image");}
        if(signal?.aborted)return unavailable();
        let result:unknown;
        try{result=await options.importImage(image,request.deliveryId);}catch{return facts("unknown");}
        if(!result || typeof result!=="object" || Array.isArray(result))return facts("unknown");
        const row=result as Record<string,unknown>;
        if(row.ok===true && row.status==="applied" && row.verified===true && row.kind===request.kind){
          const verified=appearanceControlResult(request,{schemaVersion:1,operation:"import",kind:request.kind,code:"applied",verified:true,selection:row.selection});
          return verified.code==="applied"?verified:facts("unknown");
        }
        return facts(row.status==="not_applied"?"not_applied":"unknown");
      }catch{return unavailable();}finally{importing=false;}
    })();
    if(!signal)return work;
    let onAbort:(()=>void)|undefined;
    try{return await Promise.race([work,new Promise<Record<string,unknown>>(resolve=>{onAbort=()=>resolve(unavailable());signal.addEventListener("abort",onAbort,{once:true});if(signal.aborted)onAbort();})]);}
    finally{if(onAbort)signal.removeEventListener("abort",onAbort);}
  };
}
