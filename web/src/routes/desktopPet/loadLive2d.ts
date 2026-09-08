import type { Live2dModule } from "./live2dContract";

// One local Core load per renderer window; assets are never fetched from a CDN.
let runtime: Promise<Live2dModule> | undefined;
const runtimeUrl = "/desktop-pet/live2d/runtime.js";
export function loadLive2d(): Promise<Live2dModule> {
  runtime ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/desktop-pet/live2d/Core/live2dcubismcore.min.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Live2D Core could not be loaded"));
    document.head.append(script);
  }).then(() => import(/* @vite-ignore */ runtimeUrl) as Promise<Live2dModule>);
  return runtime;
}
