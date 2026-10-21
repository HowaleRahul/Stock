import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import axios from 'axios'
import './index.css'
import App from './App.tsx'

const currentUrl = new URL(window.location.href)
const hasLegacyApiKey = currentUrl.searchParams.has('api_key') || currentUrl.searchParams.has('apiKey')
if (hasLegacyApiKey) {
  currentUrl.searchParams.delete('api_key')
  currentUrl.searchParams.delete('apiKey')
  window.history.replaceState(
    window.history.state,
    '',
    `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`,
  )
}

axios.interceptors.request.use((config) => {
  try {
    const token = localStorage.getItem('signal_desk_api_key');
    if (token && !config.headers['X-API-Key']) {
      config.headers['X-API-Key'] = token;
    }
  } catch (error) {
    console.error('Unable to read the saved API key from browser storage.', error)
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
