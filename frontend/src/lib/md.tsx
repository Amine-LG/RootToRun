import { Fragment, type ReactNode } from 'react'
import { CodeBlock } from '../components/Code'
import { canonical } from './urls'

// A small Markdown renderer for trusted, local content: headings, paragraphs, lists, code blocks,
// tables, blockquotes, inline code, bold, italics and links. No HTML is ever injected.
function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\([^)\s]+\))/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const t = m[0]
    const k = `${key}-${i++}`
    if (t.startsWith('`')) out.push(<code key={k} className={t.length <= 26 ? 'nb' : undefined}>{t.slice(1, -1)}</code>)
    else if (t.startsWith('**')) out.push(<strong key={k}>{inline(t.slice(2, -2), i)}</strong>)
    else if (t.startsWith('*')) out.push(<em key={k}>{inline(t.slice(1, -1), i)}</em>)
    else {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(t)!
      const raw = mm[2]
      // Only web links and in-app paths: no javascript:, data: or other schemes from content. An in-app path written
      // with an id (/lesson/<id>, /lab/<id>) becomes the page's readable address (lib/urls.ts).
      const href = /^\/(?!\/)/.test(raw) ? canonical(raw) : /^(https?:\/\/|mailto:|#)/.test(raw) ? raw : '#'
      const external = /^https?:/.test(href)
      out.push(
        <a key={k} href={href} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}>
          {mm[1]}
        </a>,
      )
    }
    last = m.index + t.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** A table row's cells. A `|` inside inline code or written as `\|` belongs to the cell, not the table. */
export function splitRow(line: string): string[] {
  const body = line.trim().replace(/^\|/, '').replace(/(?<!\\)\|$/, '')
  const cells: string[] = []
  let cur = ''
  let code = false
  for (let k = 0; k < body.length; k++) {
    const ch = body[k]
    if (ch === '\\' && body[k + 1] === '|') {
      cur += '|'
      k++
    } else if (ch === '`') {
      code = !code
      cur += ch
    } else if (ch === '|' && !code) {
      cells.push(cur.trim())
      cur = ''
    } else cur += ch
  }
  cells.push(cur.trim())
  return cells
}

export function Md({ text, className }: { text: string; className?: string }) {
  const lines = (text || '').replace(/\r/g, '').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let k = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i++
      continue
    }
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim()
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++])
      i++
      blocks.push(
        <CodeBlock key={k++} code={buf.join('\n')} lang={lang} />,
      )
      continue
    }
    const h = /^(#{1,4})\s+(.*)/.exec(line)
    if (h) {
      const Tag = (`h${Math.min(h[1].length + 2, 6)}`) as 'h3'
      blocks.push(<Tag key={k++}>{inline(h[2])}</Tag>)
      i++
      continue
    }
    if (line.startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        const cells = splitRow(lines[i])
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells)
        i++
      }
      const [head, ...body] = rows
      blocks.push(
        <div className={`table-wrap ${head.length >= 3 ? 'stack-on-phone' : ''}`} key={k++}>
          <table>
            <thead>
              <tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr>
            </thead>
            <tbody>
              {body.map((r, ri) => (
                <tr key={ri}>{r.map((c, j) => <td key={j} data-label={(head[j] || '').replace(/[`*]/g, '')}>{inline(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items: string[] = []
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        let item = lines[i].replace(/^\s*([-*]|\d+\.)\s+/, '')
        i++
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) item += ' ' + lines[i++].trim()
        items.push(item)
      }
      const L = ordered ? 'ol' : 'ul'
      blocks.push(
        <L key={k++}>
          {items.map((it, j) => (
            <li key={j}>{inline(it, j)}</li>
          ))}
        </L>,
      )
      continue
    }
    if (line.startsWith('>')) {
      const buf: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) buf.push(lines[i++].replace(/^>\s?/, ''))
      blocks.push(<blockquote key={k++}>{inline(buf.join(' '))}</blockquote>)
      continue
    }
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\||>|\s*([-*]|\d+\.)\s+)/.test(lines[i])) buf.push(lines[i++])
    blocks.push(<p key={k++}>{inline(buf.join(' '))}</p>)
  }
  return <div className={`md ${className || ''}`}>{blocks.map((b, j) => <Fragment key={j}>{b}</Fragment>)}</div>
}

/** One line of inline Markdown (code, bold, italics, links) without block wrappers. */
export function MdInline({ text }: { text: string }) {
  return <>{inline(text || '')}</>
}
