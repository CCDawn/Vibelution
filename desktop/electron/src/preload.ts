import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke("launcher:get-version")
});
