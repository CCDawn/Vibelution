import { describe,it,expect } from "vitest";
import { parseMainControlClaim,projectMainControlResult } from "../src/assistant/mainControlTransport.js";
const deliveryId="a".repeat(32);
describe("private appearance control protocol",()=>{
 it("accepts only closed native theme and image intents",()=>{
  expect(parseMainControlClaim({schemaVersion:1,request:{deliveryId,action:"launcher_theme_set",operation:"set",theme:"dark"}})).toMatchObject({theme:"dark"});
  for(const extra of [{path:"C:/secret.png"},{kind:"avatar",timeoutMs:120001},{kind:"avatar",timeoutMs:0}]) expect(()=>parseMainControlClaim({schemaVersion:1,request:{deliveryId,action:"operator_image_upload",operation:"import",...extra}})).toThrow();
 });
 it("never promotes an unobserved theme or arbitrary result fields",()=>{
  const req=parseMainControlClaim({schemaVersion:1,request:{deliveryId,action:"launcher_theme_set",operation:"set",theme:"dark"}})!;
  expect(projectMainControlResult(req,{schemaVersion:1,operation:"set",code:"applied",theme:"light"})).toMatchObject({code:"unavailable"});
  expect(projectMainControlResult(req,{schemaVersion:1,operation:"set",code:"applied",theme:"dark"})).toMatchObject({code:"applied",theme:"dark"});
 });
 it("keeps user images on fixed logical resource paths",()=>{
  const req=parseMainControlClaim({schemaVersion:1,request:{deliveryId,action:"operator_image_upload",operation:"import",kind:"avatar",timeoutMs:120000}})!;
  const good={schemaVersion:1,operation:"import",kind:"avatar",code:"applied",verified:true,selection:"workspace/user_avatars/a.png"};
  expect(projectMainControlResult(req,good)).toEqual(good);
  for(const selection of ["C:/x.png","workspace/user_avatars/../a.png","theme_backgrounds/a.png"]) expect(projectMainControlResult(req,{...good,selection})).toMatchObject({code:"unavailable",verified:false});
 });
});
