// Shell commands and language hints for lesson code. Kept separate from the lazy YAML/JSON grammars.
// Whitespace is never changed: the tokens of a line, joined, are exactly that line.
export type Lang = 'yaml' | 'shell' | 'json' | 'plain'
export type Tok = { c: string; s: string } // c: CSS class suffix ('' = plain)

const t = (c: string, s: string): Tok => ({ c, s })

export function langOf(hint: string | undefined, code = ''): Lang {
  const h = (hint || '').trim().toLowerCase()
  if (/^(ya?ml)$/.test(h) || /\.ya?ml\b/.test(h)) return 'yaml'
  if (h === 'json' || /\.json\b/.test(h)) return 'json'
  if (/^(bash|sh|shell|console|zsh)$/.test(h) || /\.sh\b/.test(h)) return 'shell'
  if (h === 'plain' || h === 'text' || h === 'txt' || h === 'output') return 'plain'
  if (h && !/[\s./]/.test(h)) return 'plain' // another language's name; a caption or a file name of another kind still lets the code decide
  const first = code.split('\n').find((l) => l.trim() && !l.trim().startsWith('#')) || ''
  // an object, or an array of values; not a shell prompt such as [learner@workstation ~]$
  if (/^\s*(\{|\[\s*($|[{["\d\-\]]|true|false|null))/.test(first)) return 'json'
  if (/^\s*(---|- |[\w.\-/"']+:(\s|$))/.test(first)) return 'yaml'
  return 'plain'
}

/** Shell: command names, options, strings, comments, operators and `\` continuations. State runs across lines. */
export function highlightShell(lines: string[]): Tok[][] {
  let quote: string | null = null // a quote left open at the end of the previous line
  let expectCmd = true
  return lines.map((line) => {
    const out: Tok[] = []
    let i = 0
    let word = '' // an unquoted run being built
    let wordStart = true
    const flush = () => {
      if (!word) return
      let cls = ''
      if (/^\w+=/.test(word) && wordStart) cls = ''
      else if (expectCmd && wordStart) { cls = 'bin'; expectCmd = false }
      else if (/^-[^\s]/.test(word) && wordStart) cls = 'opt'
      else if (wordStart) expectCmd = false
      out.push(t(cls, word))
      word = ''
    }
    if (!line.trim() && quote === null) return line ? [t('', line)] : []
    while (i < line.length) {
      const ch = line[i]
      if (quote) {
        let j = i
        while (j < line.length && line[j] !== quote) j += quote === '"' && line[j] === '\\' ? 2 : 1
        if (j < line.length) { out.push(t('str', line.slice(i, j + 1))); i = j + 1; quote = null } else { out.push(t('str', line.slice(i))); i = line.length }
        wordStart = false
        continue
      }
      if (ch === ' ' || ch === '\t') {
        flush()
        const m = /^[ \t]+/.exec(line.slice(i))![0]
        out.push(t('', m)); i += m.length; wordStart = true
        continue
      }
      if (ch === '#' && wordStart && !word) { out.push(t('com', line.slice(i))); i = line.length; break }
      if (ch === '"' || ch === "'") { flush(); out.push(t('str', ch)); quote = ch; i++; if (wordStart) expectCmd = false; wordStart = false
        // the quoted run starts here; the loop's quote branch finishes it
        continue }
      if (ch === '\\' && i === line.length - 1) { flush(); out.push(t('punct', '\\')); i++; continue }
      if (ch === '\\' && i + 1 < line.length) { word += line.slice(i, i + 2); i += 2; continue }
      const ph = wordStart && !word ? /^<[A-Za-z][^<>\n]*>/.exec(line.slice(i)) : null
      if (ph) { flush(); out.push(t('ph', ph[0])); i += ph[0].length; expectCmd = false; wordStart = false; continue }
      const op = /^(\|\||&&|\||;|&|>>|>|<|\d?>&\d)/.exec(line.slice(i))
      if (op && !(ch === '&' && word)) { flush(); out.push(t('punct', op[0])); i += op[0].length; expectCmd = !/^\d?>&|>|<|>>/.test(op[0]); wordStart = true; continue }
      word += ch; i++
    }
    flush()
    return out
  })
}

export const plainLines = (lines: string[]): Tok[][] => lines.map((l) => (l ? [t('', l)] : []))

export const canHighlight = (code: string): boolean => code.length <= 50_000 && !code.split('\n').some((l) => l.length > 2_000)
