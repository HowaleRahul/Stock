import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import axios from 'axios'
import './index.css'
import App from './App.tsx'

// Intercept axios requests to attach API Key for production environments
axios.interceptors.request.use((config) => {
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const apiKeyFromUrl = urlParams.get('api_key') || urlParams.get('apiKey');
    if (apiKeyFromUrl) {
      localStorage.setItem('signal_desk_api_key', apiKeyFromUrl);
    }
    const token = localStorage.getItem('signal_desk_api_key');
    if (token && !config.headers['X-API-Key']) {
      config.headers['X-API-Key'] = token;
    }
  } catch {
    // Ignore storage errors in restricted contexts
  }
  return config;
});

// Intercept axios responses to detect 403 Forbidden and prompt for API authentication
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 403) {
      window.dispatchEvent(new CustomEvent('signal-desk-auth-required'));
    }
    return Promise.reject(error);
  }
);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
