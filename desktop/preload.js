const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  onInit: (cb) => ipcRenderer.on('prompt:init', (_e, payload) => cb(payload)),
  submit: (instruction) => ipcRenderer.invoke('prompt:submit', instruction),
  close: () => ipcRenderer.send('prompt:close'),
});
