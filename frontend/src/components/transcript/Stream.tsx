import { Fragment, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { CopyButton } from '../ui'
import { revealStart } from '../../lib/reveal'
import { lineClass, parseOutput, shortCell, visibleColumns, type OutputTable } from './parse'
import '../transcript.css'

export function Marked({ text, q }: { text: string; q?: string }) {
  if (!q) return <>{text}</>
  const parts: ReactNode[] = [], lower = text.toLowerCase(), needle = q.toLowerCase()
  let i = 0, k = 0
  for (;;) { const j = lower.indexOf(needle, i); if (j < 0) break; parts.push(text.slice(i, j), <mark key={k++}>{text.slice(j, j + q.length)}</mark>); i = j + q.length }
  return <>{parts}{text.slice(i)}</>
}

function Table({ data, q }: { data: OutputTable; q?: string }) {
  const root = useRef<HTMLDivElement>(null), table = useRef<HTMLTableElement>(null)
  const [cards, setCards] = useState(false)
  useLayoutEffect(() => {
    const el = root.current; if (!el) return
    let alive = true
    const measure = () => {
      if (!alive || !table.current) return
      const font = parseFloat(getComputedStyle(table.current!).fontSize) || 14
      const minWidth = data.head.reduce((sum, head, col) => {
        const compact = data.rows.filter(row => shortCell(head, row[col])).map(row => row[col].length)
        return sum + Math.max(head.length, ...compact, 8) * font * .62 + font
      }, 0)
      setCards(el.clientWidth < 600 || minWidth > el.clientWidth)
    }
    const ro = new ResizeObserver(measure); ro.observe(el); measure(); document.fonts?.ready.then(measure)
    return () => { alive = false; ro.disconnect() }
  }, [data])
  const cell = (text: string, head: string) => /^(PORTS?)$/.test(head) && text.includes(',')
    ? text.split(/(,\s*)/).map((part, i) => i % 2 ? <Fragment key={i}>{part}<wbr /></Fragment> : <span key={i} className={shortCell(head, part) ? 'tx-token' : ''}><Marked text={part} q={q} /></span>)
    : <Marked text={text} q={q} />
  return <div className={`tx-table-wrap transcript-table ${cards ? 'transcript-cards-mode' : ''}`} ref={root}>
    <table className="tx-table" ref={table} hidden={cards}><thead><tr>{data.head.map((h, i) => <th key={i} scope="col">{h}</th>)}</tr></thead>
      <tbody>{data.rows.map((row, i) => <tr key={i}>{row.map((value, j) => <td key={j} className={`${shortCell(data.head[j], value) ? 'tx-short' : 'tx-long'} ${lineClass(value)}`}>{cell(value, data.head[j])}</td>)}</tr>)}</tbody>
    </table>
    <ul className="transcript-row-cards" hidden={!cards} aria-label="Output table rows">{data.rows.map((row, i) => <li key={i}><dl>
      {data.head.map((h, j) => <Fragment key={j}><dt>{h}</dt><dd className={`${shortCell(h, row[j]) ? 'tx-short' : 'tx-long'} ${lineClass(row[j])}`}>{row[j] ? cell(row[j], h) : '—'}</dd></Fragment>)}
    </dl></li>)}</ul>
  </div>
}

export type Truncation = { omitted?: number; position?: 'start' | 'end'; reason?: string }
/** The visual parser may trim/split for display only. Copy buttons always receive the original string. */
export function Stream({ text, err, q, maxLines = 40, wrap = true, truncation }: { text: string; err?: boolean; q?: string; maxLines?: number; wrap?: boolean; truncation?: Truncation }) {
  const blocks = useMemo(() => parseOutput(text), [text]), lines = text.split(/\r?\n/).length
  const [all, setAll] = useState(false)
  const limit = all ? Infinity : maxLines, hidden = Math.max(0, lines - maxLines)
  if (!text) return null
  return <div className={`transcript-stream ${wrap ? 'transcript-wrap' : 'transcript-raw'}`}>
    <div className="transcript-stream-tools"><span>{err ? 'stderr' : 'stdout'}</span><CopyButton text={text} label={err ? 'Copy stderr' : 'Copy stdout'} /></div>
    {truncation && <p className="transcript-note" role="note">Source truncated this stream{truncation.omitted != null ? ` (${truncation.omitted} characters omitted at the ${truncation.position || 'end'})` : ''}. {truncation.reason || 'Copy contains the retained output only.'}</p>}
    {blocks.filter(b => b.start < limit).map(b => {
      const shown = b.lines.slice(0, Math.max(0, limit - b.start))
      if (wrap && !err && b.table && shown.length > 1) return <Table key={b.start} data={visibleColumns({ head: b.table.head, rows: b.table.rows.slice(0, shown.length - 1) }, wrap)} q={q} />
      return <pre key={b.start} className={err ? 'tx-err' : 'tx-out'}>{shown.map((l, i) => <span key={i} data-ln={b.start + i} className={`ln ${lineClass(l, !!err)}`} style={{ paddingInlineStart: `${Math.min(l.length - l.trimStart().length, 32)}ch`, textIndent: `${-Math.min(l.length - l.trimStart().length, 32)}ch` }}><Marked text={l || '\u00a0'} q={q} /></span>)}</pre>
    })}
    {hidden > 0 && <div className="transcript-preview-note"><button className="tx-more" aria-expanded={all} onClick={(e) => {
      const box = e.currentTarget.closest('.transcript-stream')
      const expanding = !all
      setAll(!all)
      // show the first newly revealed line (a text line or a table row) from the top, not the far end of the output
      if (expanding) requestAnimationFrame(() => revealStart(box?.querySelector(`[data-ln="${maxLines}"]`) || box?.querySelectorAll('tbody tr')[maxLines - 1] || null))
    }}>{all ? 'Show fewer lines' : `Show ${hidden} more retained lines`}</button>
      <span>{all ? `All ${lines} retained lines shown.` : `Preview: ${Math.min(lines, maxLines)} of ${lines} retained lines. Copy includes all retained bytes.`}</span></div>}
  </div>
}
