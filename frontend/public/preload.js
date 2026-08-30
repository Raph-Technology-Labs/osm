// contextBridge IPC surface, adapted from gcm's preload.js -- generalized to
// per-camera-id handlers since OSM needs N simultaneous feeds, not one.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("ipc", {
  handleCameraFeedMessages: (cameraId, callback) =>
    ipcRenderer.on(`MessageType.CameraFeed.${cameraId}`, (_event, value) => callback(value)),
  handleInspectionResultMessages: (callback) =>
    ipcRenderer.on("MessageType.InspectionResult", (_event, value) => callback(value)),
});
