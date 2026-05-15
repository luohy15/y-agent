import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('renderer: missing #root');

// No StrictMode: window.api.onInit registers an ipcRenderer.on listener with
// no cleanup, and StrictMode's double-mount in dev would attach it twice.
createRoot(container).render(<App />);
