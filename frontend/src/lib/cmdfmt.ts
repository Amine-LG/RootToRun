// How a one-line shell command is displayed so that it can be read without scrolling sideways.
//
//   1. Several commands joined by `;` are shown one per line. Only a `;` that ends a top-level command is replaced by
//      a newline: never one inside quotes, `$(...)`, backticks, `${...}`, parentheses, `{ ...; }` groups,
//      `[[ ... ]]`, or `if/for/while/until/select ... fi/done` constructs, and never one after a comment.
//   2. A command that is still longer than its box is continued with " \" + newline + two spaces: before each
//      top-level `|`, `&&` and `||` first (one pipeline stage per line), then before options (`--x`, `-x`) where a
//      stage is still too long, and only if that is not enough, before any other word.
//
// The displayed text is a valid script with exactly the same meaning: at top level a newline ends a command as `;`
// does, and bash removes every backslash-newline before it reads words. Commands this module cannot read with
// certainty (here-documents, `case`, `function`, `coproc`, `alias`, unbalanced quotes or brackets, a comment inside
// a substitution, text that already spans several lines) are shown exactly as written. So are commands whose behaviour
// depends on the physical lines of the input, where a newline or a backslash-newline would change what they do:
// `$LINENO` and `BASH_LINENO` (the line number), `caller` (the caller's line), `shopt` (a parse-time option such as
// extglob applies only to the lines read after it) and `set -v` / `set -o verbose` (echoes the lines as read). Copy buttons copy the
// original single line, as recorded (see Code.tsx and Flow.tsx).

type Cut = { at: number; end: number } // a whitespace run [at, end) where a line may be cut

/** What a scan of one line found: where it may be cut. */
type Scan = {
  seps: number[] // offsets of the `;` that end a top-level command
  opBreaks: Cut[] // before a top-level `|`, `|&`, `&&` or `||`, outside any compound command
  optBreaks: Cut[] // before an option word, outside parentheses and substitutions
  wordBreaks: Cut[] // before any other word there: used only when options alone cannot make a line fit
}

const META = new Set([' ', '\t', ';', '&', '|', '(', ')', '<', '>'])
const OPENERS: Record<string, string> = { if: 'fi', for: 'done', while: 'done', until: 'done', select: 'done', '{': '}', '[[': ']]' }
const KEEP_CMDPOS = new Set(['then', 'else', 'elif', 'do', '!', 'time', 'if', 'while', 'until', '{'])
const REFUSED = new Set(['case', 'esac', 'function', 'coproc', 'alias'])
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=/

// what behaves differently once one input line becomes several (see the header); a false match only means a command
// is shown as written
const LINE_SENSITIVE = /LINENO|\b(caller|shopt)\b|\bset\s+([-+][A-Za-z]*v|[-+]o\s+verbose\b)/

class Refuse extends Error {}

const opensNested = (s: string, j: number) => {
  const c = s[j]
  return c === "'" || c === '"' || c === '`' || (c === '$' && (s[j + 1] === '(' || s[j + 1] === '{' || s[j + 1] === "'"))
}

/** End offset (exclusive) of the quoted string or expansion that starts at `i`. Throws Refuse on what it cannot model. */
function skipQuoted(s: string, i: number): number {
  const ch = s[i]
  if (ch === "'") {
    const j = s.indexOf("'", i + 1)
    if (j < 0) throw new Refuse()
    return j + 1
  }
  if (ch === '"') {
    let j = i + 1
    while (j < s.length) {
      const c = s[j]
      if (c === '\\') j += 2
      else if (c === '"') return j + 1
      else if (c === '`' || (c === '$' && (s[j + 1] === '(' || s[j + 1] === '{'))) j = skipQuoted(s, j)
      else j++
    }
    throw new Refuse()
  }
  if (ch === '`' || (ch === '$' && s[i + 1] === "'")) {
    const close = ch === '`' ? '`' : "'"
    let j = ch === '`' ? i + 1 : i + 2
    while (j < s.length) {
      if (s[j] === '\\') j += 2
      else if (s[j] === close) return j + 1
      else j++
    }
    throw new Refuse()
  }
  if (ch === '$' && s[i + 1] === '{') {
    let j = i + 2
    let depth = 1
    while (j < s.length) {
      const c = s[j]
      if (c === '\\') j += 2
      else if (opensNested(s, j)) j = skipQuoted(s, j)
      else if (c === '{') { depth++; j++ }
      else if (c === '}') { if (--depth === 0) return j + 1; j++ }
      else j++
    }
    throw new Refuse()
  }
  // $( ... ), $(( ... )), <( ... ), >( ... ): a nested command, balanced in parentheses
  let j = i + 2
  let depth = 1
  let wordStart = true
  while (j < s.length) {
    const c = s[j]
    if (c === '\\') { j += 2; wordStart = false; continue }
    if (opensNested(s, j) || ((c === '<' || c === '>') && s[j + 1] === '(')) { j = skipQuoted(s, j); wordStart = false; continue }
    if (c === '<' && s[j + 1] === '<' && s[j + 2] !== '<') throw new Refuse() // a here-document
    if (wordStart && (c === '#' || /^(case|esac)([\s;)]|$)/.test(s.slice(j, j + 5)))) throw new Refuse() // a comment would swallow the `)`; case patterns are unbalanced
    if (c === '(') depth++
    else if (c === ')' && --depth === 0) return j + 1
    wordStart = META.has(c)
    j++
  }
  throw new Refuse()
}

/** Scan one line of shell at top level; null when the line holds something this module does not model. */
export function scan(s: string): Scan | null {
  const out: Scan = { seps: [], opBreaks: [], optBreaks: [], wordBreaks: [] }
  const stack: string[] = [] // the closers expected: 'fi', 'done', '}', ']]', ')'
  let cmdPos = true // the next word is in command position, where bash recognises reserved words
  let forHead = false // inside `for NAME in WORDS`: the words up to `;` or `do` are not commands
  let i = 0
  try {
    while (i < s.length) {
      const c = s[i]
      if (c === ' ' || c === '\t') {
        let j = i
        while (j < s.length && (s[j] === ' ' || s[j] === '\t')) j++
        if (i > 0 && j < s.length && !stack.includes(')')) {
          const next = s.slice(j)
          if (/^(\|\||&&|\|)/.test(next)) { if (!stack.length) out.opBreaks.push({ at: i, end: j }) }
          else if (/^--?[A-Za-z0-9]/.test(next)) out.optBreaks.push({ at: i, end: j })
          else out.wordBreaks.push({ at: i, end: j })
        }
        i = j
        continue
      }
      if (c === '#') break // words are read whole below, so this `#` starts a word: a comment, nothing after it is touched
      if (c === ';') {
        if (s[i + 1] === ';' || s[i + 1] === '&') throw new Refuse() // `;;` and `;&` belong to case
        if (!stack.length) out.seps.push(i)
        cmdPos = true
        forHead = false
        i++
        continue
      }
      if (c === '&' || c === '|') {
        if (c === '&' && s[i + 1] === '>') { i += s[i + 2] === '>' ? 3 : 2; continue } // &> and &>> redirect output
        i += s[i + 1] === c || (c === '|' && s[i + 1] === '&') ? 2 : 1
        cmdPos = true
        continue
      }
      if (c === '(') {
        stack.push(')')
        cmdPos = true
        i++
        continue
      }
      if (c === ')') {
        if (stack.pop() !== ')') throw new Refuse()
        cmdPos = s[i - 1] === '(' // `name()` is followed by the function's body, a compound command
        i++
        continue
      }
      if (c === '<' || c === '>') {
        if (s[i + 1] === '(') { i = skipQuoted(s, i); cmdPos = false; continue } // process substitution
        if (c === '<' && s[i + 1] === '<' && s[i + 2] !== '<') throw new Refuse() // a here-document
        let j = i + 1
        while (j < s.length && '<>&|'.includes(s[j])) j++
        i = j
        continue // the redirection's target is the next word; the command position does not change
      }
      // a word: unquoted characters, quoted strings and expansions up to the next metacharacter
      const start = i
      let plain = true
      while (i < s.length && !META.has(s[i])) {
        if (s[i] === '\\') { plain = false; i += 2; continue }
        if (opensNested(s, i)) { plain = false; i = skipQuoted(s, i); continue }
        i++
      }
      if (i > s.length) throw new Refuse() // a trailing backslash
      const w = s.slice(start, i)
      if (plain && REFUSED.has(w)) throw new Refuse()
      if (forHead) {
        if (plain && w === 'do') { forHead = false; cmdPos = true }
        continue
      }
      if (plain && w === ']]' && stack[stack.length - 1] === ']]') { stack.pop(); cmdPos = false; continue }
      if (plain && cmdPos) {
        if (w in OPENERS) stack.push(OPENERS[w])
        else if ((w === 'fi' || w === 'done' || w === '}') && stack.pop() !== w) throw new Refuse()
        if (w === 'for' || w === 'select') { forHead = true; cmdPos = false; continue }
        cmdPos = KEEP_CMDPOS.has(w) || ASSIGNMENT.test(w)
        continue
      }
      cmdPos = cmdPos && ASSIGNMENT.test(w) // assignments before a command keep the command position
    }
    if (stack.length || forHead) return null
  } catch (e) {
    if (e instanceof Refuse) return null
    throw e
  }
  return out
}

/** One displayed line, and whether it continues the previous one (after " \") or starts a new command. */
export type CmdLine = { text: string; cont: boolean }

/** Cut a text at the given whitespace runs, greedily, so that each line fits `width` (the first line starts with
 *  `first`, later ones with two spaces). */
function fill(text: string, pts: Cut[], width: number, first: string): string[] {
  const room = width - 2 // keep room for " \"
  const lines: string[] = []
  let start = 0
  let prefix = first
  let cand: Cut | null = null
  const cut = (p: Cut) => {
    lines.push(prefix + text.slice(start, p.at))
    start = p.end
    prefix = '  '
    cand = null
  }
  // a line never holds a command name alone (`| grep` then its options on the next line): cut after two words at least
  const enough = (p: Cut) => {
    const words = text.slice(start, p.at).trim().replace(/^(\|\||&&|\|&?)\s*/, '').split(/\s+/)
    return words.length >= 2 || words[0].startsWith('-')
  }
  for (let k = 0; k < pts.length; k++) {
    const p = pts[k]
    if (p.at <= start || !enough(p)) continue
    if (prefix.length + p.at - start > room) {
      if (cand) {
        cut(cand)
        k-- // look at this point again on the new line
      } else cut(p)
    } else cand = p
  }
  if (cand && prefix.length + text.length - start > room) cut(cand)
  lines.push(prefix + text.slice(start))
  return lines
}

/** A line still too long after the cuts before options (a long name or annotation with no option near it) is also
 *  cut before other words, never between an option and its value. */
function refine(line: string, width: number): string[] {
  if (line.length <= width) return [line]
  const prefix = line.startsWith('  ') ? '  ' : ''
  const body = line.slice(prefix.length)
  const sc = scan(body)
  if (!sc) return [line]
  const afterOption = (c: Cut) => /(^|\s)-[^\s]*$/.test(body.slice(0, c.at))
  return fill(body, [...sc.optBreaks, ...sc.wordBreaks.filter((c) => !afterOption(c))].sort((a, b) => a.at - b.at), width, prefix)
}

/** Lay out one command that holds no top-level `;`. */
function layout(cmd: string, width: number): CmdLine[] {
  const sc = cmd.length > width ? scan(cmd) : null
  if (!sc) return [{ text: cmd, cont: false }]
  // one pipeline stage (or one && / || operand) per line, then options within a stage that is still too long
  const bounds = [{ at: 0, end: 0 }, ...sc.opBreaks, { at: cmd.length, end: cmd.length }]
  const out: CmdLine[] = []
  for (let k = 0; k + 1 < bounds.length; k++) {
    const from = bounds[k].end
    const to = bounds[k + 1].at
    const within = (cuts: Cut[]) => cuts.filter((p) => p.at > from && p.at < to).map((p) => ({ at: p.at - from, end: p.end - from }))
    for (const ln of fill(cmd.slice(from, to), within(sc.optBreaks), width, k ? '  ' : ''))
      for (const piece of refine(ln, width)) out.push({ text: piece, cont: out.length > 0 })
  }
  return out
}

/** The lines a command is displayed on. Joined (a `cont` line after " \" + newline, any other after a newline),
 *  they form a script that bash reads as exactly the same commands as the original. */
export function commandLines(cmd: string, width = 78): CmdLine[] {
  if (/[\n\r]/.test(cmd) || LINE_SENSITIVE.test(cmd)) return [{ text: cmd, cont: false }]
  const sc = cmd.includes(';') ? scan(cmd) : null
  if (!sc || !sc.seps.length) return layout(cmd, width)
  const parts: string[] = []
  let from = 0
  for (const at of sc.seps) {
    parts.push(cmd.slice(from, at).trim())
    from = at + 1
  }
  parts.push(cmd.slice(from).trim())
  if (!parts[parts.length - 1]) parts.pop() // a trailing `;`
  if (parts.some((p) => !p)) return [{ text: cmd, cont: false }] // `; a` or `a; ; b`: not a plain list
  // `a\ ; b`: the space before the `;` is escaped (part of the word). Trimmed, the line would end in a backslash and
  // bash would join it to the next line: such a list is shown as written.
  if (parts.some((p) => /(^|[^\\])(\\\\)*\\$/.test(p))) return [{ text: cmd, cont: false }]
  return parts.flatMap((p) => layout(p, width))
}

/** The displayed text of a command: one line per top-level command, long ones continued with " \". */
export function formatCommand(cmd: string, width = 78): string {
  return commandLines(cmd, width)
    .map((l, i) => (i === 0 ? l.text : l.cont ? ` \\\n${l.text}` : `\n${l.text}`))
    .join('')
}
