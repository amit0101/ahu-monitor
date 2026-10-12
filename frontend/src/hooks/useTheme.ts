// hooks/useTheme.ts — Light/dark theme manager
//
// Reads from localStorage, applies data-theme to <html>, exposes toggle.
// Default: 'light' (clean machine-monitoring panel aesthetic).

import { useState, useEffect, useCallback } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'aq-theme'
const DEFAULT: Theme = 'light'

function applyTheme(t: Theme) {
  if (t === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as Theme | null
      return stored === 'dark' || stored === 'light' ? stored : DEFAULT
    } catch {
      return DEFAULT
    }
  })

  // Apply on mount and on change
  useEffect(() => {
    applyTheme(theme)
    try { localStorage.setItem(STORAGE_KEY, theme) } catch { /* */ }
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggleTheme }
}
