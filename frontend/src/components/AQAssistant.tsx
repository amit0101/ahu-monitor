// components/AQAssistant.tsx — GPT-4o powered conversational assistant
//
// Sends context-enriched prompts to /api/assistant (Phase 2 endpoint).
// For now uses direct OpenAI API call via the system context built from
// the Zustand store — plant state is injected into the prompt automatically.

import { useState, useRef, useEffect } from 'react'
import { useTwinStore } from '../stores/useTwinStore'
import { getApiUrl } from '../config'

// ── Lightweight markdown renderer ─────────────────────────────────────────────
// Handles: **bold**, - bullet list items, blank-line paragraph breaks.
// No external dependency — keeps the bundle lean.
function renderMarkdown(text: string) {
  // Split into lines, group consecutive bullet lines into <ul> blocks
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  let bulletBuffer: string[] = []

  function flushBullets(key: string) {
    if (bulletBuffer.length === 0) return
    elements.push(
      <ul key={key} style={{ margin: '4px 0 4px 0', paddingLeft: 16 }}>
        {bulletBuffer.map((b, i) => (
          <li key={i} style={{ marginBottom: 2 }}>{applyInline(b)}</li>
        ))}
      </ul>
    )
    bulletBuffer = []
  }

  lines.forEach((line, idx) => {
    const trimmed = line.trim()
    if (/^[-*]\s+/.test(trimmed)) {
      bulletBuffer.push(trimmed.replace(/^[-*]\s+/, ''))
    } else {
      flushBullets(`ul-${idx}`)
      if (trimmed === '') {
        // blank line → small spacer (skip if elements is empty)
        if (elements.length > 0) {
          elements.push(<div key={`sp-${idx}`} style={{ height: 4 }} />)
        }
      } else {
        elements.push(<div key={`l-${idx}`}>{applyInline(trimmed)}</div>)
      }
    }
  })
  flushBullets('ul-end')
  return <>{elements}</>
}

// Converts **bold** spans within a line to <strong>
function applyInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} style={{ color: 'var(--color-text)', fontWeight: 600 }}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const SYSTEM_PROMPT = `You are the aQ Assistant, an expert predictive maintenance AI embedded in a real-time
Air Handling Unit (AHU) monitoring dashboard. You have access to live sensor data, 
component health scores, active alerts, and Remaining Useful Life estimates.

Answer questions about:
- Current AHU health and fault status
- Root cause analysis of active alerts
- Maintenance recommendations and scheduling
- Interpretation of sensor trends (vibration, temperature, pressure, current)
- General HVAC/predictive maintenance engineering

Keep answers concise, engineering-focused, and actionable.
Use the current system context provided in the user message to give specific answers.`

function buildContext(store: ReturnType<typeof useTwinStore.getState>): string {
  const { snapshot, alerts, recommendations, simStatus } = store
  const lines: string[] = ['=== CURRENT SYSTEM STATE ===']

  if (simStatus) {
    lines.push(`Simulation Day: ${simStatus.sim_day.toFixed(0)} / ${simStatus.total_days}`)
  }

  if (snapshot?.health) {
    lines.push('\nComponent Health:')
    Object.entries(snapshot.health).forEach(([id, h]) => {
      const name = id.split('.').slice(-1)[0] || id
      lines.push(`  ${name}: ${Math.round(h.health * 100)}% (${h.state})${h.fault !== 'none' ? ` — ${h.fault}` : ''}`)
    })
  }

  const activeAlerts = alerts.filter((a) => !a.acknowledged).slice(0, 5)
  if (activeAlerts.length > 0) {
    lines.push('\nActive Alerts:')
    activeAlerts.forEach((a) => {
      lines.push(`  [${a.severity.toUpperCase()}] ${a.title}: ${a.description}`)
    })
  }

  if (recommendations.length > 0) {
    lines.push('\nTop Maintenance Recommendation:')
    lines.push(`  ${recommendations[0].action} — ${recommendations[0].rationale}`)
  }

  return lines.join('\n')
}

const QUICK_PROMPTS = [
  "What's causing the current alerts?",
  "When should I replace the bearings?",
  "What does the filter ΔP trend indicate?",
  "Summarize the AHU health status",
]

export default function AQAssistant() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { setSnapshot: _ss, setWsConnected: _swsc } = useTwinStore()

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  const send = async (userText: string) => {
    if (!userText.trim() || loading) return
    const context = buildContext(useTwinStore.getState())
    const userMsg: Message = {
      role: 'user',
      content: `${context}\n\n=== USER QUESTION ===\n${userText}`,
    }
    setMessages((prev) => [...prev, { role: 'user', content: userText }])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(getApiUrl('/assistant'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(25000),
        body: JSON.stringify({
          messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            ...messages.map((m) => ({ role: m.role, content: m.content })),
            userMsg,
          ],
        }),
      })
      if (!res.ok) {
        const errText = await res.text().catch(() => '')
        throw new Error(`API error ${res.status}${errText ? `: ${errText}` : ''}`)
      }
      const data = await res.json()
      const reply = data.content ?? data.choices?.[0]?.message?.content ?? 'No response.'
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `⚠ Unable to reach AI Assistant: ${msg}` },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '12px 12px', overflow: 'hidden' }}>
      <div className="panel-title">
        aQ Assistant
        <span style={{ float: 'right', fontSize: 9, color: 'var(--color-blue)', fontWeight: 400, letterSpacing: 0 }}>
          GPT-4o · context-aware
        </span>
      </div>

      {/* Chat messages */}
      <div
        ref={scrollRef}
        style={{ flex: 1, overflowY: 'auto', marginBottom: 6, display: 'flex', flexDirection: 'column', gap: 6 }}
      >
        {messages.length === 0 && (
          <div style={{ padding: '8px 0' }}>
            <div style={{ fontSize: 10, color: 'var(--color-text-mute)', marginBottom: 6 }}>Quick questions:</div>
            {QUICK_PROMPTS.map((q) => (
              <button
                key={q}
                className="btn"
                style={{ fontSize: 10, padding: '3px 8px', marginBottom: 4, display: 'block', width: '100%', textAlign: 'left' }}
                onClick={() => send(q)}
              >
                {q}
              </button>
            ))}
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: msg.role === 'assistant' ? '96%' : '88%',
              background: msg.role === 'user' ? 'var(--color-blue-dim)' : 'var(--color-surface2)',
              border: `1px solid ${msg.role === 'user' ? 'rgba(15,122,192,0.3)' : 'var(--color-border)'}`,
              borderRadius: msg.role === 'user' ? '8px 8px 2px 8px' : '8px 8px 8px 2px',
              padding: '7px 11px',
              fontSize: 11,
              lineHeight: 1.65,
              color: 'var(--color-text)',
              animation: 'fadeIn 0.2s ease',
            }}
          >
            {msg.role === 'assistant' ? renderMarkdown(msg.content) : msg.content}
          </div>
        ))}

        {loading && (
          <div style={{
            alignSelf: 'flex-start',
            background: 'var(--color-surface2)',
            border: '1px solid var(--color-border)',
            borderRadius: '8px 8px 8px 2px',
            padding: '6px 10px',
            fontSize: 11,
            color: 'var(--color-text-dim)',
          }}>
            <span style={{ animation: 'pulse 1s ease-in-out infinite', display: 'inline-block' }}>●</span>
            <span style={{ margin: '0 3px', animation: 'pulse 1s ease-in-out infinite 0.2s', display: 'inline-block' }}>●</span>
            <span style={{ animation: 'pulse 1s ease-in-out infinite 0.4s', display: 'inline-block' }}>●</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div style={{ display: 'flex', gap: 5, flexShrink: 0 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send(input)}
          placeholder="Ask about AHU health…"
          style={{
            flex: 1,
            background: 'var(--color-surface2)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            padding: '5px 9px',
            fontSize: 11,
            color: 'var(--color-text)',
            fontFamily: 'var(--font-sans)',
            outline: 'none',
          }}
        />
        <button
          className="btn btn-primary"
          style={{ padding: '5px 10px', fontSize: 11 }}
          onClick={() => send(input)}
          disabled={loading}
        >
          ↑
        </button>
      </div>
    </div>
  )
}
