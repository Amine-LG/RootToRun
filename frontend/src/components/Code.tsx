// Code shown in lessons: highlighted (YAML, shell, JSON), exact whitespace, with a copy button. Commands that are too
// long for their box are shown over several lines (lib/cmdfmt.ts); copying always gives the original text.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { formatCommand } from '../lib/cmdfmt'
import { canHighlight, highlightShell, langOf, plainLines, type Tok } from '../lib/highlight-shell'
import { t } from '../lib/i18n'
import { CopyButton } from './ui'

export function Toks({ toks }: { toks: Tok[] }) {
  return (
    <>
      {toks.map((k, i) => (k.c ? <span key={i} className={`tok-${k.c}`}>{k.s}</span> : k.s))}
    </>
  )
}

/** How many characters of the element's own font fit on one line (it updates when the box or the fonts change). */
export function useCols(ref: React.RefObject<HTMLElement | null>, deflt = 78): number {
  const [cols, setCols] = useState(deflt)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const cs = getComputedStyle(el)
      const cv = document.createElement('canvas').getContext('2d')
      if (!cv || !el.clientWidth) return
      cv.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
      const w = cv.measureText('0'.repeat(20)).width / 20
      const inner = el.clientWidth - parseFloat(cs.paddingLeft || '0') - parseFloat(cs.paddingRight || '0')
      if (w > 0) setCols(Math.max(24, Math.min(140, Math.floor(inner / w) - 1)))
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(el)
    document.fonts?.ready.then(measure).catch(() => undefined)
    return () => ro?.disconnect()
  }, [ref])
  return cols
}

/** A shell command, highlighted and (when long) split over several lines. */
export function ShellText({ cmd, cols }: { cmd: string; cols: number }) {
  const rows = useMemo(() => highlightShell(formatCommand(cmd, cols).split('\n')), [cmd, cols])
  return (
    <>
      {rows.map((r, i) => (
        <span key={i}>
          {i > 0 && '\n'}
          <Toks toks={r} />
        </span>
      ))}
    </>
  )
}

/** Syntax-highlighted code with a header bar (file name or language) and a copy button. */
export function CodeBlock({ code, lang, caption, highlight = [], label }: { code: string; lang?: string; caption?: string; highlight?: string[]; label?: string }) {
  const text = code.replace(/\n$/, '')
  const lg = langOf(lang || caption, text)
  const initial = useMemo(() => lg === 'shell' && canHighlight(text) ? highlightShell(text.split('\n')) : plainLines(text.split('\n')), [lg, text])
  const [ready, setReady] = useState<{ text: string; lang: string; rows: Tok[][] } | null>(null)
  useEffect(() => {
    if ((lg !== 'yaml' && lg !== 'json') || !canHighlight(text)) return
    let active = true
    import('../lib/highlight').then(({ highlight }) => {
      if (active) setReady({ text, lang: lg, rows: highlight(lg, text) })
    }).catch(() => undefined) // the plain rows remain usable if loading fails
    return () => { active = false }
  }, [lg, text])
  const rows = ready?.text === text && ready.lang === lg ? ready.rows : initial
  const lines = text.split('\n')
  return (
    <div className="codebox" data-lang={lg}>
      <div className="codebar">
        <span className="file-name mono">{caption || (lg === 'plain' ? t('ui.codeText') : lg)}</span>
        <CopyButton text={code} label={label || t('ui.copyCode')} showLabel />
      </div>
      <pre className="code" tabIndex={0} aria-label={caption || undefined}>
        <code>
          {rows.map((r, i) => (
            <span key={i} className={`demo-line ${highlight.some((h) => h && lines[i].includes(h)) ? 'hl' : ''}`}>
              <Toks toks={r} />
              {'\n'}
            </span>
          ))}
        </code>
      </pre>
    </div>
  )
}
