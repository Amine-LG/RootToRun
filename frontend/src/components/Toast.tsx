import { useSyncExternalStore } from 'react'
import { Icon } from './ui'

// Small, polite notifications (e.g. "Lesson completed +20 XP"), with an optional celebration burst.
type Toast = { id: number; title: string; body?: string; tone?: 'ok' | 'info' }
let toasts: Toast[] = []
const subs = new Set<() => void>()
let next = 1
const emit = () => subs.forEach((f) => f())

export function toast(title: string, body?: string, tone: 'ok' | 'info' = 'ok', celebrate = false) {
  const id = next++
  toasts = [...toasts, { id, title, body, tone }].slice(-3)
  emit()
  window.setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== id)
    emit()
  }, 4200)
  if (celebrate) burst()
}

/** A short burst of particles near the top-right of the content (skipped with reduced motion). */
export function burst(x = window.innerWidth - 120, y = window.innerHeight - 80) {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  const el = document.createElement('div')
  el.className = 'burst'
  el.style.left = `${x}px`
  el.style.top = `${y}px`
  el.setAttribute('aria-hidden', 'true')
  for (let i = 0; i < 18; i++) {
    const p = document.createElement('i')
    const a = (Math.PI * 2 * i) / 18 + Math.random() * 0.4
    const r = 60 + Math.random() * 70
    p.style.setProperty('--dx', `${Math.cos(a) * r}px`)
    p.style.setProperty('--dy', `${Math.sin(a) * r - 40}px`)
    p.style.setProperty('--r', `${Math.random() * 360}deg`)
    el.appendChild(p)
  }
  document.body.appendChild(el)
  window.setTimeout(() => el.remove(), 1000)
}

export function Toasts() {
  const list = useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => toasts,
  )
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((x) => (
        <div key={x.id} className={`toast ${x.tone || ''}`}>
          <Icon name={x.tone === 'ok' ? 'check' : 'info'} size={18} />
          <div>
            <strong>{x.title}</strong>
            {x.body && <span className="small muted">{x.body}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}
