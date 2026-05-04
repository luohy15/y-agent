const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  onInit: (cb) => ipcRenderer.on('prompt:init', (_e, payload) => cb(payload)),
  onResult: (cb) => ipcRenderer.on('result:show', (_e, payload) => cb(payload)),
  submit: (instruction, mode) => ipcRenderer.invoke('prompt:submit', { instruction, mode }),
  close: () => ipcRenderer.send('prompt:close'),
  closeResult: () => ipcRenderer.send('result:close'),
});
