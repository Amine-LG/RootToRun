export type OutputTable = { head: string[]; rows: string[][] }
export type OutputBlock = { start: number; lines: string[]; table: OutputTable | null }

function expandTabs(s: string) {
  let out = ''
  for (const c of s) out += c === '\t' ? ' '.repeat(8 - out.length % 8) : c
  return out
}

/** Parse only aligned uppercase CLI tables. Raw streams remain separate and are never reconstructed for copying. */
export function parseTable(input: string[]): OutputTable | null {
  const lines = input.map(expandTabs), header = lines[0] || ''
  if (lines.length < 2 || !/^[A-Z][A-Z0-9_ ()/.-]*(?: {2,}[A-Z][A-Z0-9_ ()/.-]*)+\s*$/.test(header)) return null
  const columns = [...header.matchAll(/\S+(?: \S+)*/g)]
  if (columns.length < 2) return null
  const starts = columns.map(c => c.index!)
  const cut = (line: string) => starts.map((x, i) => line.slice(x, starts[i + 1]).trim())
  const rows: string[][] = []
  for (const line of lines.slice(1)) {
    if (!line.trim()) continue
    if (starts.slice(1).some(x => line.length > x && !/\s/.test(line[x - 1]))) return null
    rows.push(cut(line))
  }
  return rows.length ? { head: cut(header), rows } : null
}

export function visibleColumns(table: OutputTable, wrap = true): OutputTable {
  const cols = table.head.map((_, i) => i).filter(i => !wrap || table.rows.some(row => row[i] !== ''))
  return { head: cols.map(i => table.head[i]), rows: table.rows.map(row => cols.map(i => row[i])) }
}
export function shortCell(header: string, value: string): boolean {
  if (!value) return true
  if (/^(READY|STATUS|RESTARTS|AGE|PORTS?|CPU|MEMORY|AVAILABLE|UPDATED|DESIRED|CURRENT|UP-TO-DATE)$/.test(header)) return value.length <= 32 && !/[\s,]/.test(value)
  return value.length <= 12 && !/\s/.test(value)
}
export function parseOutput(text: string): OutputBlock[] {
  const lines = text.split(/\r?\n/), blocks: OutputBlock[] = []
  let start = 0
  for (let i = 0; i <= lines.length; i++) {
    if (i !== lines.length && lines[i].trim()) continue
    if (i > start) { const part = lines.slice(start, i); blocks.push({ start, lines: part, table: parseTable(part) }) }
    if (i < lines.length) blocks.push({ start: i, lines: [lines[i]], table: null })
    start = i + 1
  }
  return blocks
}

export function lineClass(line: string, err = false): string {
  if (err || /\b(Forbidden|BackOff|denied|NotFound|OOMKilled|CrashLoop|ErrImagePull|ProgressDeadlineExceeded)\b|^(error|Error|fatal|FATAL)\b/.test(line)) return 'o-err'
  return /^(Warning|W\d{4})|warning:/.test(line) ? 'o-warn' : ''
}
