import type React from 'react'

/** Arrow keys move and select within a group of role="radio" buttons (one Tab stop for the group, as native radios). */
export function radioKeys(e: React.KeyboardEvent<HTMLElement>) {
  const keys: Record<string, number> = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }
  if (!(e.key in keys)) return
  const radios = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('[role=radio]:not(:disabled)')]
  const at = radios.indexOf(document.activeElement as HTMLButtonElement)
  const next = radios[(at + keys[e.key] + radios.length) % radios.length]
  if (!next) return
  e.preventDefault()
  next.focus()
  next.click()
}
