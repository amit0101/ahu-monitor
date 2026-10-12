// config.ts — Centralized API and WebSocket configuration
//
// In local development, defaults to relative paths:
//   API: /api/* (proxied by Vite to http://localhost:8000)
//   WS:  /ws/live (proxied by Vite to ws://localhost:8000)
//
// For production deployments (e.g. Vercel frontend + Render backend):
//   Set VITE_API_URL to your backend URL (e.g. https://ahu-monitor-backend.onrender.com)
//   The WebSocket URL and API endpoints will be automatically derived.

const RAW_API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.trim()?.replace(/\/+$/, '')

export function getApiUrl(path: string): string {
  const cleanPath = path.startsWith('/') ? path : `/${path}`
  if (!RAW_API_URL) {
    return `/api${cleanPath}`
  }
  if (RAW_API_URL.endsWith('/api')) {
    return `${RAW_API_URL}${cleanPath}`
  }
  return `${RAW_API_URL}/api${cleanPath}`
}

export function getWsUrl(): string {
  const customWs = (import.meta.env.VITE_WS_URL as string | undefined)?.trim()
  if (customWs) {
    return customWs
  }

  if (RAW_API_URL && RAW_API_URL.startsWith('http')) {
    try {
      const url = new URL(RAW_API_URL)
      const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${protocol}//${url.host}/ws/live`
    } catch {
      // Fallback below
    }
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/live`
}
