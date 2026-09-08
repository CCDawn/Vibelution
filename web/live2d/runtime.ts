/**
 * Vibelution's local Cubism adapter. Built separately because the official
 * Framework uses pre-ES2022 class-field semantics. No application/session API.
 */
import { CubismFramework } from '@framework/live2dcubismframework';
import { CubismUserModel } from '@framework/model/cubismusermodel';
import { CubismEyeBlink } from '@framework/effect/cubismeyeblink';
import { CubismBreath, BreathParameterData } from '@framework/effect/cubismbreath';
import { CubismMatrix44 } from '@framework/math/cubismmatrix44';
import { CubismMotion } from '@framework/motion/cubismmotion';
import { CubismShaderManager_WebGL } from '@framework/rendering/cubismshader_webgl';
import { CubismWebGLOffscreenManager } from '@framework/rendering/cubismoffscreenmanager';
import type { PetAnimationState } from '../src/api/types/petActivity';
import type { Live2dController, Live2dStatus } from '../src/routes/desktopPet/live2dContract';

const ASSETS = '/desktop-pet/live2d/';
const id = (value:string) => CubismFramework.getIdManager().getId(value);
type Manifest = {FileReferences:{Moc:string;Physics:string;Textures:string[];Motions:Record<string,{File:string}[]>};Groups:{Name:string;Ids:string[]}[]};

class XiaoLuoModel extends CubismUserModel {
 greeting: CubismMotion;
 async setup(read:(path:string)=>Promise<ArrayBuffer>) {
  const manifest:Manifest = JSON.parse(new TextDecoder().decode(await read('小洛.model3.json')));
  this.loadModel(await read(manifest.FileReferences.Moc),true);
  const physics=await read(manifest.FileReferences.Physics);
  this.loadPhysics(physics,physics.byteLength);

  this._eyeBlink=CubismEyeBlink.create();
  this._eyeBlink.setParameterIds(['ParamEyeLOpen','ParamEyeROpen'].map(id));
  this._eyeBlink.setBlinkingInterval(3);
  this._breath=CubismBreath.create();
  this._breath.setParameters([
   new BreathParameterData(id('ParamBreath'),.5,.5,3.6,1),
   new BreathParameterData(id('ParamAngleZ'),0,1.8,5.2,1),
   new BreathParameterData(id('ParamBodyAngleX'),0,1.1,6.4,1)
  ]);
  const bytes=await read(manifest.FileReferences.Motions['Tap头'][0].File);
  this.greeting=this.loadMotion(bytes,bytes.byteLength,'greeting');
  this.greeting.setFadeInTime(.2); this.greeting.setFadeOutTime(.2);
  this.greeting.setEffectIds(
   ['ParamEyeLOpen','ParamEyeROpen'].map(id),
   []
  );
  this._model.saveParameters();
  return manifest.FileReferences.Textures;
 }
 change(state:PetAnimationState,animate:boolean) {
  this._motionManager.stopAllMotions();
  if(state==='celebrating' && animate) this._motionManager.startMotionPriority(this.greeting,false,3);
 }
 update(dt:number,time:number,state:PetAnimationState,x:number,y:number) {
  this._model.loadParameters();
  this._motionManager.updateMotion(this._model,dt);
  this._eyeBlink.updateParameters(this._model,dt);
  this._breath.updateParameters(this._model,dt);
  this._dragManager.set(x,y); this._dragManager.update(dt);
  const add=(key:string,value:number)=>this._model.addParameterValueById(id(key),value);
  add('ParamAngleZ',this._dragManager.getX()*15); add('ParamAngleY',this._dragManager.getY()*16);
  add('ParamEyeBallX',this._dragManager.getX()*.8); add('ParamEyeBallY',this._dragManager.getY()*.65);
  if(state==='thinking'){add('ParamAngleZ',-9);add('ParamEyeBallY',.35);}
  if(state==='reading'){add('ParamAngleY',-12);add('ParamEyeBallY',-.5);add('ParamEyeBallX',Math.sin(time)*.2);}
  if(state==='waiting'){add('Param61',1);add('ParamAngleZ',7);add('ParamBrowLY',.2);add('ParamBrowRY',.2);}
  if(state==='alert'){add('ParamBrowLY',.6);add('ParamBrowRY',.6);add('ParamMouthOpenY',.25);}
  if(state==='tooling'){add('ParamAngleX',Math.sin(time*1.4)*5);add('ParamAngleY',-6);}
  if(state==='verifying'){add('ParamAngleZ',5);add('ParamEyeBallX',Math.sin(time*.8)*.3);}
  if(state==='answering') add('ParamMouthOpenY',.12+Math.abs(Math.sin(time*7))*.4);
  if(state==='celebrating'){add('Param88',1);add('ParamMouthForm',.8);add('ParamAngleZ',Math.sin(time*2)*3);}
  this._physics.evaluate(this._model,dt);
  this._model.update();
 }
 draw(width:number,height:number) {
  const matrix=new CubismMatrix44();
  matrix.scale(height/width,1); this._modelMatrix.setHeight(1.92);
  matrix.multiplyByMatrix(this._modelMatrix);
  const renderer=this.getRenderer();
  renderer.setMvpMatrix(matrix);
  renderer.setRenderState(null,[0,0,width,height]); renderer.drawModel(ASSETS+'Shaders/');
 }
}

export function createLive2dController(canvas:HTMLCanvasElement, initialState:PetAnimationState, report:(status:Live2dStatus)=>void):Live2dController {
 const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:true,antialias:true});
 if(!gl) throw new Error('WebGL is unavailable');
 if(!CubismFramework.isInitialized()){CubismFramework.startUp();CubismFramework.initialize();}
 const model=new XiaoLuoModel();
 const abort=new AbortController();
 const motion=matchMedia('(prefers-reduced-motion: reduce)');
 const textures:WebGLTexture[]=[];
 let state=initialState, disposed=false, loaded=false, released=false, ready=false;
 let raf=0,last=0,time=0,x=0,y=0,dirty=true;
 function release() {
  if(released) return;
  released=true;
  model.release(); textures.forEach(texture=>gl.deleteTexture(texture));
  if(model.greeting) CubismMotion.delete(model.greeting);
 }
 async function read(path:string) {
  const response=await fetch(ASSETS+'XiaoLuo/'+path,{signal:abort.signal});
  if(!response.ok) throw new Error('Live2D asset: '+response.status);
  const bytes=await response.arrayBuffer(); abort.signal.throwIfAborted(); return bytes;
 }
 function size() {
  const ratio=Math.min(devicePixelRatio,2);
  const width=Math.max(1,Math.round(canvas.clientWidth*ratio));
  const height=Math.max(1,Math.round(canvas.clientHeight*ratio));
  if(width!==canvas.width || height!==canvas.height) {
   canvas.width=width;canvas.height=height;dirty=true;
   if(model.getRenderer()) model.setRenderTargetSize(width,height);
  }
 }
 function schedule() {cancelAnimationFrame(raf);if(!disposed && loaded && !document.hidden) raf=requestAnimationFrame(frame);}
 function frame(now:number) {
  if(disposed || document.hidden) return;
  if(now-last<1000/30 && !dirty){schedule();return;}
  const dt=Math.min((now-last)/1000 || 1/30,1/15);last=now;size();
  try {
   if(CubismShaderManager_WebGL.getInstance().getShader(gl)._isShaderLoaded) {
    if(!ready){ready=true;dirty=true;model.change(state,!motion.matches);report('ready');}
    if(dirty || !motion.matches) {
     if(!motion.matches) time+=dt;
     model.update(motion.matches?0:dt,time,state,motion.matches?0:x,motion.matches?0:y);
     gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.viewport(0,0,canvas.width,canvas.height);
     gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
     const offscreen=CubismWebGLOffscreenManager.getInstance();
     offscreen.beginFrameProcess(gl);model.draw(canvas.width,canvas.height);
     offscreen.endFrameProcess(gl);offscreen.releaseStaleRenderTextures(gl);dirty=false;
    }
   }
  } catch(error){report('error');console.error('Live2D rendering failed',error);dispose();return;}
  if(!motion.matches || !ready) schedule();
 }
 function pointer(event:PointerEvent) {
  if(event.buttons || motion.matches) return;
  const rect=canvas.getBoundingClientRect();
  x=Math.max(-1,Math.min(1,(event.clientX-rect.left)/rect.width*2-1));
  y=Math.max(-1,Math.min(1,1-(event.clientY-rect.top)/rect.height*2));
 }
 function resetPointer(){x=0;y=0;}
 function visibility(){last=performance.now();dirty=true;schedule();}
 function reduced(){resetPointer();dirty=true;if(ready)model.change(state,false);schedule();}
 function lost(event:Event){event.preventDefault();report('error');dispose();}
 function dispose() {
  if(disposed)return;disposed=true;abort.abort();cancelAnimationFrame(raf);resize.disconnect();
  canvas.removeEventListener('pointermove',pointer);canvas.removeEventListener('pointerleave',resetPointer);
  canvas.removeEventListener('webglcontextlost',lost);
  document.removeEventListener('visibilitychange',visibility);motion.removeEventListener('change',reduced);
  if(loaded) release();
 }
 const resize=new ResizeObserver(()=>{dirty=true;size();schedule();});
 resize.observe(canvas);
 canvas.addEventListener('pointermove',pointer);canvas.addEventListener('pointerleave',resetPointer);
 canvas.addEventListener('webglcontextlost',lost);
 document.addEventListener('visibilitychange',visibility);motion.addEventListener('change',reduced);
 void (async()=>{
  try {
   const files=await model.setup(read);size();
   model.createRenderer(canvas.width,canvas.height);model.getRenderer().startUp(gl);
   model.getRenderer().setIsPremultipliedAlpha(true);
   for(const [index,file] of files.entries()) {
    const bytes=await read(file);
    const url=URL.createObjectURL(new Blob([bytes]));
    const image=new Image();
    try {image.src=url;await image.decode();abort.signal.throwIfAborted();}
    finally {URL.revokeObjectURL(url);}
    const texture=gl.createTexture();if(!texture)throw new Error('Live2D texture allocation failed');
    textures.push(texture);gl.bindTexture(gl.TEXTURE_2D,texture);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,1);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    model.getRenderer().bindTexture(index,texture);
   }
   gl.bindTexture(gl.TEXTURE_2D,null);
   model.getRenderer().loadShaders(ASSETS+'Shaders/');
   loaded=true;schedule();
  }catch(error){
   release();
   if(!disposed){report('error');console.error('Live2D loading failed',error);dispose();}
  }
 })();
 return {setState(next){if(next===state)return;state=next;dirty=true;if(ready)model.change(state,!motion.matches);schedule();},dispose};
}
