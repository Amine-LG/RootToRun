// Matching typed commands against the corpus of recorded commands (practice terminal).
import type { CommandRef } from './data'

export const norm = (s: string) => s.trim().replace(/\s+/g, ' ')

/** A typed command in a comparable form: runs of spaces collapse to one and spacing around `|`, `||`, `&&` and `;`
 *  is made uniform, but only outside quotes, where spaces are part of the value (`"My  Report.txt"` and
 *  `"My Report.txt"` name different files). A trailing `;` is dropped. */
export function normCommand(s: string): string {
  let out = ''
  let seg = ''
  let quote: string | null = null
  const flush = () => {
    out += seg.replace(/[ \t]*(\|\||&&|\||;)[ \t]*/g, ' $1 ').replace(/[ \t]+/g, ' ')
    seg = ''
  }
  const src = s.replace(/^[ \t]+|[ \t]+$/g, '')
  for (let k = 0; k < src.length; k++) {
    const ch = src[k]
    if (quote) {
      out += ch
      if (quote === '"' && ch === '\\' && k + 1 < src.length) out += src[++k] // \" stays inside the quotes
      else if (ch === quote) quote = null
    } else if (ch === '\\' && k + 1 < src.length) {
      seg += '\u0003' // an escaped character is kept as typed, including an escaped blank
      flush()
      out = out.slice(0, -1) + ch + src[++k]
    } else if (ch === "'" || ch === '"') {
      flush()
      quote = ch
      out += ch
    } else seg += ch
  }
  flush()
  return out.replace(/^ | $/g, '').replace(/ ?;$/, '')
}

// Plain Kubernetes commands, which `kubectl` and `oc` run identically. Only for these may a typed `kubectl …` be
// answered with a recording made with `oc …`, and the answer then says so. OpenShift commands (new-project,
// expose, adm, start-build…) and `create`, whose kinds differ, never are.
const PLAIN = new Set(['get', 'describe', 'logs', 'explain', 'api-resources', 'api-versions', 'apply', 'delete', 'scale', 'rollout', 'exec', 'label', 'annotate', 'top', 'events', 'diff', 'patch', 'wait'])
/** `oc …` for a typed `kubectl …` plain Kubernetes command, or null. */
export const ocEquivalent = (typed: string) => {
  const w = norm(typed).split(' ')
  return w[0] === 'kubectl' && PLAIN.has(w[1]) ? ['oc', ...w.slice(1)].join(' ') : null
}

const tokens = (s: string) => norm(s).replace(/^kubectl\b/, 'oc').toLowerCase().split(/[\s=/,.:'"{}()[\]-]+/).filter((x) => x.length > 1)

/** Exact match on what the learner sees (cmd) or on what really ran (run). A plain Kubernetes `kubectl` command may
 * match a recording made with `oc`; `viaOc` then says so, so that the answer can name the client really used. */
export function exact(list: CommandRef[], typed: string): (CommandRef & { viaOc?: boolean }) | undefined {
  const find = (n: string) => list.find((c) => c.tested && (norm(c.cmd) === n || (c.run && norm(c.run) === n)))
  const direct = find(norm(typed))
  if (direct) return direct
  const oc = ocEquivalent(typed)
  const viaOc = oc ? find(oc) : undefined
  return viaOc ? { ...viaOc, viaOc: true } : undefined
}

/** Closest recorded commands: same verb first, then shared words. */
export function similar(list: CommandRef[], typed: string, max = 6): CommandRef[] {
  const tt = new Set(tokens(typed))
  const verb = norm(typed).split(' ')[1]
  const seen = new Set<string>()
  return list
    .filter((c) => c.tested)
    .map((c) => {
      const ct = tokens(c.cmd)
      const shared = ct.filter((x) => tt.has(x)).length
      return { c, score: shared + (c.cmd.split(' ')[1] === verb ? 3 : 0) - ct.length * 0.02 }
    })
    .filter((x) => x.score > 1)
    .sort((a, b) => b.score - a.score)
    .filter((x) => (seen.has(x.c.cmd) ? false : (seen.add(x.c.cmd), true)))
    .slice(0, max)
    .map((x) => x.c)
}

export { plain, search, searchRanked } from './search'

// ---------------------------------------------------------------- typed-command equivalence (nothing is executed)
// A deliberately small model of a command line, enough to accept the forms of one command that mean the same thing,
// and strict wherever it does not know the program. Every rule here was checked against the real shell and the real
// programs (scripts/grading_oracle.py; its results are kept in oracle.fixtures.json and replayed by the tests).
//
// The shell. Words are split as bash splits them (only spaces and tabs separate words), quotes are removed, and
// quoting is tracked per character: what bash would expand is kept apart from what was typed literally, so
// `oc get user ~` (bash passes the home directory) never matches `oc get user '~'`, and `*'.log'` (the `*` is still
// a pattern) never matches `'*.log'`. Tilde expansion is modelled exactly (a word-start `~`, `~/`, `~user`, and `~`
// after `=` or `:` in an assignment, unless any part of the prefix is quoted, even by empty quotes); a line that uses
// other expansions (variables, command substitution, brace expansion, history `!`), escapes or shell syntax (pipes,
// `;`, `&&`, redirections, comments) is only accepted when it matches an accepted form exactly, character for
// character apart from runs of spaces.
//
// The program. The program name must match exactly (`summarise.sh` is not `./summarise.sh`).
// - oc, kubectl, podman, skopeo and helm are parsed the way their own parser (cobra and pflag) parses them, from a
//   model generated from each program's real help (climodel.json, scripts/cli_model.py): the command path and its
//   aliases (`create cm`), each option's long name, whether it takes a value, may stand alone or be repeated. So
//   `-n x`, `-nx`, `-n=x` and `--namespace=x` are one option anywhere on the line; an unknown option, a missing value
//   or a single-value option given twice makes the line exact-only; repeated options keep their order. For oc and
//   kubectl a resource kind may be written with any of the names the cluster's API discovery gives it.
// - Other programs: options keep their order, except a run of single-letter options that the program documents as
//   taking no value (SHORT_BOOL), which may be reordered and grouped (`ls -la` = `ls -a -l`). `--name=value` is never
//   assumed to equal `--name value` (it does not for options without a value, or with an optional one). `./x` = `x`
//   only for the operands of programs whose operands are all paths (PATH_OPERANDS), and `x/` = `x` only for programs
//   whose operands must be directories (cd, mkdir, rmdir). A trailing `--` is kept.

import CLI from './climodel.json'

// glob: the word holds a `*`, `?` or `[` that bash would treat as a pattern (not quoted)
type Tok = { v: string; quoted: boolean; lead: string; glob: boolean } // lead: the unquoted start, before any quote

// text the shell replaces (`~` becomes the home directory): never equal to anything typed literally
const EXPANDED = '\u0001'
// a word bash would expand as a filename pattern: never equal to the same characters quoted
const PATTERN = '\u0002'

type Ch = { c: string; q: string } // a character of a word and the quote it was typed in ('' when unquoted)

/** True when bash would apply brace expansion to the word (`{a,b}`, `{1..3}`): not modelled. */
function braces(cs: Ch[]): boolean {
  for (let i = 0; i < cs.length; i++) {
    if (cs[i].c !== '{' || cs[i].q) continue
    const j = cs.findIndex((x, k) => k > i && x.c === '}' && !x.q)
    if (j < 0) return false
    const inner = cs.slice(i + 1, j)
    if (inner.some((x) => x.c === ',' && !x.q)) return true
    const text = inner.map((x) => x.c).join('')
    if (inner.every((x) => !x.q) && /^(-?\d+\.\.-?\d+|[A-Za-z]\.\.[A-Za-z])(\.\.-?\d+)?$/.test(text)) return true
  }
  return false
}

/** One word after quote removal, with tilde expansion and filename patterns marked. `quotes` holds the positions
 *  (in `cs`) where a quoted part began, empty quotes included. */
function word(cs: Ch[], quoted: boolean, quotes: Set<number>): Tok | null {
  if (braces(cs)) return null
  const mark = new Set<number>() // positions where a tilde-prefix starts
  const prefix = (i: number, stop: string) => {
    // a tilde-prefix runs to the next unquoted stop character; it expands only when none of it is quoted
    let j = i + 1
    while (j < cs.length && !(stop.includes(cs[j].c) && !cs[j].q)) {
      if (cs[j].q) return
      j++
    }
    for (const at of quotes) if (at > i && at <= j) return // empty quotes inside the prefix count too: ~'' or ~""/x
    mark.add(i)
  }
  if (cs[0]?.c === '~' && !cs[0].q && !quotes.has(0)) prefix(0, '/')
  const text = cs.map((x) => x.c).join('')
  const assign = /^[A-Za-z_][A-Za-z0-9_]*=/.exec(text)
  if (assign && cs.slice(0, assign[0].length).every((x) => !x.q) && ![...quotes].some((at) => at < assign[0].length)) {
    for (let i = assign[0].length; i < cs.length; i++)
      if (cs[i].c === '~' && !cs[i].q && (i === assign[0].length || (cs[i - 1].c === ':' && !cs[i - 1].q))) prefix(i, '/:')
  }
  let v = ''
  let lead: string | null = null
  cs.forEach((x, i) => {
    if ((x.q || quotes.has(i)) && lead === null) lead = v
    v += (mark.has(i) ? EXPANDED : '') + x.c
  })
  const glob = cs.some((x) => !x.q && /[*?[]/.test(x.c))
  // in a pattern, a quoted pattern character is literal and an unquoted one is not: keep the difference
  if (glob) v = cs.map((x, i) => (mark.has(i) ? EXPANDED : '') + (x.q && /[*?[\]\\]/.test(x.c) ? '\\' + x.c : x.c)).join('')
  return { v, quoted, lead: quoted ? lead ?? v : v, glob }
}

// a `!` that interactive bash replaces from the history: one followed by a character other than a blank, `=` or `(`
const history = (s: string, k: number) => k + 1 < s.length && !/[ \t=("]/.test(s[k + 1])
const BLANK = /[ \t]/ // bash's word separators: a no-break space or any other Unicode space is part of a word

/** Split a command line into words as bash does; null when it holds shell syntax or expansions this model does not
 *  interpret (only an exact match can then accept it). */
export function shellWords(s: string): Tok[] | null {
  const out: Tok[] = []
  let cs: Ch[] = []
  let quotes = new Set<number>()
  let quoted = false
  let inWord = false
  let q: string | null = null
  const src = s.replace(/^[ \t]+|[ \t]+$/g, '')
  const push = () => {
    const w = word(cs, quoted, quotes)
    if (w) out.push(w)
    return !!w
  }
  for (let k = 0; k < src.length; k++) {
    const ch = src[k]
    if (q) {
      if (ch === q) q = null
      else {
        if (q === '"' && (/[$`\\]/.test(ch) || (ch === '!' && history(src, k)))) return null // expansion inside double quotes: not modelled
        cs.push({ c: ch, q })
      }
      continue
    }
    if (ch === "'" || ch === '"') {
      q = ch
      quoted = true
      inWord = true
      quotes.add(cs.length)
    } else if (BLANK.test(ch)) {
      if (inWord && !push()) return null
      cs = []
      quotes = new Set()
      quoted = false
      inWord = false
    } else if (/[|;&<>`$()\\\n\r]/.test(ch) || (ch === '!' && history(src, k)) || (ch === '#' && !inWord)) return null
    else {
      cs.push({ c: ch, q: '' })
      inWord = true
    }
  }
  if (q) return null
  if (inWord && !push()) return null
  return out
}

// single-letter options that each program documents as taking no value (GNU coreutils, grep, procps, iproute2 man
// pages): a run of them may be reordered and grouped. Letters that take a value (`grep -e`, `ls -I`, `ps -o`,
// `uniq -f`, `head -n`…) are left out, so a group containing one is compared as typed.
const SHORT_BOOL: Record<string, string> = {
  ls: 'aAbBcCdfFgGhHiklLmnNopqQrRsStuUvxXZ1', cp: 'abdfHilLnPprRsuvx', mv: 'bfinuvT', rm: 'dfiIrRv', mkdir: 'pv', rmdir: 'pv',
  cat: 'AbeEnstTuv', wc: 'clmwL', grep: 'abcEFGhHiIlLnoPqrRsTUvVwxyz', egrep: 'abchHiIlLnoqrRsTUvVwxyz', df: 'ahHiklPTv',
  du: 'abcDhHklLmPsSx0', ps: 'AadeFfHjlLMNrTXxy', sort: 'bcdfghiMmnRrsuVz', uniq: 'cdDiuz', ln: 'bfFiLnPrsTv',
  chmod: 'cfRv', chown: 'cfhHLPRv', id: 'aGgnruZz', uname: 'aimnoprsv', head: 'qvz', tail: 'FfqrvZz', free: 'bghklmtvwy',
  ss: '04689aeEHilmMnOprsStuwxZz', touch: 'achmf', tree: 'adfgilnpqstuxACDFJN', file: 'bcEhiklLNnprsSvz0',
}
// letters of one program that override each other (the last one wins), so a run holding two of them is not
// reorderable: ls's format, sort, time and listing letters, grep's matcher and output letters, size units
const CONFLICTS: Record<string, string[]> = {
  ls: ['lC1xmnogf', 'tSUXvf', 'cu', 'aAf', 'bqN', 'hk', 'sf'], grep: ['EFGP', 'clLoq', 'hH'], egrep: ['clLoq', 'hH'],
  df: ['hHk'], du: ['hHkm', 'Ls'], ps: ['lfFj'], sort: ['ghMnRV'], cp: ['fin', 'Pl', 'Ls'], mv: ['fin'], rm: ['fi'],
}
const reorderable = (program: string, run: string[]) => {
  const letters = run.map((o) => o[1])
  if (new Set(letters).size !== letters.length) return false // `-w -w` is not `-w`
  return (CONFLICTS[program] || []).every((cls) => letters.filter((c) => cls.includes(c)).length < 2)
}
// programs whose operands are all paths, where `./x` names the same file as `x`
const PATH_OPERANDS = new Set(['ls', 'cat', 'cd', 'mkdir', 'rmdir', 'rm', 'du', 'df', 'stat', 'file', 'head', 'tail', 'wc', 'touch', 'tree', 'less', 'realpath', 'cp', 'mv'])
// programs whose operands must be directories, where `dir/` = `dir`
const DIR_OPERANDS = new Set(['cd', 'mkdir', 'rmdir'])
// cobra options whose value is a path (`./x` = `x`), and those whose value must be a directory (`dir/` = `dir`)
const KUBE_PATHS = new Set(['filename', 'file', 'kustomize', 'to', 'dest-dir', 'from-file', 'sync-config', 'whitelist', 'blacklist'])
const KUBE_DIRS = new Set(['kustomize', 'to', 'dest-dir'])
// oc/kubectl options whose value is a resource reference (`--from=cronjob/x`), where kind spellings are equivalent
const KUBE_REFS = new Set(['from'])

const pathForm = (v: string, dirOnly: boolean) => {
  if (v === '/' || v === '.' || v === './') return v === './' ? '.' : v
  // a leading `./` is spelling, `.//x` is not `/x`, `x/.` requires a directory, and `a//b` is left as typed
  let p = v
  while (p.startsWith('./') && p.length > 2 && p[2] !== '/' && p[2] !== '-') p = p.slice(2)
  if (dirOnly && p.length > 1 && p.endsWith('/')) p = p.slice(0, -1)
  return p
}
/** A word as the program receives it: a pattern bash would expand is marked, a literal path may be normalised. */
const operandForm = (w: Tok, path: boolean, dirOnly: boolean) => (w.glob ? PATTERN + w.v : path ? pathForm(w.v, dirOnly) : w.v)
const isOpt = (t?: Tok) => !!t && /^-{1,2}[A-Za-z]/.test(t.lead)
const tailForm = (w: Tok) => (w.glob ? PATTERN + w.v : w.v)

// oc/kubectl resource names as the client resolves them, from the training cluster's API discovery (climodel.json,
// scripts/cli_model.py): plural, singular and short names map to `kind.group`, and a name two resources share resolves
// as the client resolves it (`ip` is IPAddress on Kubernetes 1.33+, not InstallPlan). `name.group` names that group's
// resource. Applied only where a kind is expected: the word after a reading verb, and the `kind/` of `kind/name`.
// Kinds of operators that the training cluster does not run are added by hand, plural and singular only (their short
// names could not be checked).
const KINDS_SEEN = (CLI as unknown as { kinds: { resolve: Record<string, string>; qualified: Record<string, string> } }).kinds
const KINDS_ABSENT: Record<string, string> = { clusterlogforwarder: 'clusterlogforwarder.observability.openshift.io', clusterlogforwarders: 'clusterlogforwarder.observability.openshift.io' }
const kindOf = (w: string): string | null => {
  const x = w.toLowerCase()
  return KINDS_SEEN.resolve[x] ?? KINDS_SEEN.qualified[x] ?? KINDS_ABSENT[x] ?? KINDS_ABSENT[x.replace(/\.observability\.openshift\.io$/, '')] ?? null
}
const KIND_VERBS = new Set(['get', 'describe', 'delete', 'edit', 'label', 'annotate'])
const NAME_VERBS = new Set(['get', 'describe', 'delete', 'edit'])
const kindForm = (w: string, typePosition: boolean) => {
  if (w.includes('=') || w.includes(EXPANDED) || w.includes(PATTERN)) return w // a label, or text the shell replaces: never a kind
  const slash = w.indexOf('/')
  if (slash > 0) {
    const k = kindOf(w.slice(0, slash))
    return k ? k + w.slice(slash) : w
  }
  return typePosition ? w.split(',').map((x) => kindOf(x) || x).join(',') : w
}

type Flag = { short: string; kind: 'bool' | 'value' | 'list'; default?: boolean; optional?: boolean }
type Cmd = { subs: Record<string, string[]>; aliases: string[]; flags?: Record<string, Flag> }
type Client = { version: string; globals: Record<string, Flag>; commands: Record<string, Cmd> }
const CLIENTS = CLI as unknown as Record<string, Client>
const KUBE = new Set(['oc', 'kubectl'])
// oc/kubectl options whose KEY=VALUE values set independent entries, so distinct keys may come in any order
// (helm's --set is not one: `--set a=2 --set a.b=1` fails while the reverse works)
const ORDER_FREE = new Set(['param', 'from-literal', 'env'])
// commands whose options end at the first operand: what follows belongs to the container's command
// (`podman run img sleep 1000 -d` runs `sleep 1000 -d`; checked with podman 5.8)
const NOT_INTERSPERSED: Record<string, Set<string>> = {
  podman: new Set(['run', 'create', 'exec', 'container run', 'container create', 'container exec']),
}

/** A cobra/pflag program's view of a line: its command path, positional arguments and options (long names), or null
 *  when the program would reject it (unknown option, missing value), it is ambiguous (a single-value option given
 *  twice: the program may validate the first one), or the model does not know the command. */
function cobraShape(program: string, words: Tok[]): string[] | null {
  const cli = CLIENTS[program]
  const kube = KUBE.has(program)
  const dd = words.findIndex((w) => !w.quoted && w.v === '--')
  const body = dd < 0 ? words : words.slice(0, dd)
  const tail = dd < 0 ? [] : ['--', ...words.slice(dd + 1).map(tailForm)]
  const flagOf = (cmd: Cmd, name: string, short: boolean): [string, Flag] | undefined => {
    for (const set of [cmd.flags || {}, cli.globals]) {
      if (!short && set[name]) return [name, set[name]]
      if (short) {
        const hit = Object.entries(set).find(([, f]) => f.short === name)
        if (hit) return hit
      }
    }
    return undefined
  }
  // 1. the command path: the first words naming a subcommand (or one of its aliases), options skipped, as cobra finds it
  let key = ''
  let cmd = cli.commands['']
  const pathAt = new Set<number>()
  for (let i = 0; i < body.length; i++) {
    const w = body[i]
    if (isOpt(w)) {
      const long = w.lead.startsWith('--')
      const name = long ? w.v.slice(2).split('=')[0] : w.v[1]
      const f = flagOf(cmd, name, !long)
      // like cobra, an option it does not know yet is assumed to take the next word (`oc -o yaml get pods` works,
      // `oc --no-headers get pods` does not)
      if ((!f || (f[1].kind !== 'bool' && !f[1].optional)) && !w.v.includes('=') && (long || w.v.length === 2)) i++
      continue
    }
    const sub = Object.entries(cmd.subs).find(([s, aliases]) => s === w.v || aliases.includes(w.v))
    if (w.quoted || !sub) break
    key = key ? `${key} ${sub[0]}` : sub[0]
    cmd = cli.commands[key]
    pathAt.add(i)
    if (!cmd) return null
  }
  if (!cmd.flags) return null // a command the course does not use: only an exact match can accept it
  // 2. options and positional arguments, parsed as pflag does
  const opts: [string, string][] = []
  const args: Tok[] = []
  const valueOf = (name: string, w: Tok) => {
    if (name === 'from-file' && !w.glob && w.v.includes('=')) {
      const eq = w.v.indexOf('=') // KEY=PATH: the key is a name, only the path is normalised
      return `${w.v.slice(0, eq)}=${pathForm(w.v.slice(eq + 1), false)}`
    }
    return KUBE_PATHS.has(name) ? operandForm(w, true, KUBE_DIRS.has(name)) : kube && KUBE_REFS.has(name) ? kindForm(tailForm(w), false) : tailForm(w)
  }
  const seen: string[] = []
  const add = (name: string, f: Flag, value: string) => {
    if (f.kind === 'bool' && value !== 'true' && value !== 'false') return false
    seen.push(name)
    opts.push([name, value]) // `--x` = `--x=true`; an explicit value is never treated as absent (unset can differ)
    return true
  }
  const stopAtOperand = NOT_INTERSPERSED[program]?.has(key) ?? false
  for (let i = 0; i < body.length; i++) {
    if (pathAt.has(i)) continue
    const w = body[i]
    if (!isOpt(w) || (stopAtOperand && args.length)) {
      args.push(w)
      continue
    }
    if (w.lead.startsWith('--')) {
      const eq = w.v.indexOf('=')
      const f = flagOf(cmd, (eq < 0 ? w.v : w.v.slice(0, eq)).slice(2), false)
      if (!f) return null // unknown option: the program refuses the line
      const [long, flag] = f
      let value: string
      if (eq >= 0) value = valueOf(long, { ...w, v: w.v.slice(eq + 1), lead: w.lead.slice(eq + 1) })
      else if (flag.kind === 'bool') value = 'true'
      else if (flag.optional) value = EXPANDED + 'no-value'
      else if (i + 1 < body.length) value = valueOf(long, body[++i]) // pflag takes the next word, whatever it is
      else return null // "flag needs an argument"
      if (!add(long, flag, value)) return null
      continue
    }
    // short options: `-x`, `-xv`, `-x=v`, `-x v`, and groups of options that take no value (`-it`)
    const letters = w.v.slice(1)
    for (let j = 0; j < letters.length; j++) {
      const f = flagOf(cmd, letters[j], true)
      if (!f) return null
      const [long, flag] = f
      const rest = letters.slice(j + 1)
      if (flag.kind === 'bool') {
        if (rest.startsWith('=')) {
          if (!add(long, flag, rest.slice(1))) return null
          break
        }
        add(long, flag, 'true')
        continue
      }
      let value: string
      if (rest) value = valueOf(long, { ...w, v: rest.startsWith('=') ? rest.slice(1) : rest, lead: '' })
      else if (flag.optional) value = EXPANDED + 'no-value'
      else if (i + 1 < body.length) value = valueOf(long, body[++i])
      else return null
      add(long, flag, value)
      break
    }
  }
  // a single-value option given twice: pflag keeps the last value but may first reject an earlier one
  const scalar = seen.filter((n) => (flagOf(cmd, n, false)?.[1].kind ?? 'value') !== 'list')
  if (new Set(scalar).size !== scalar.length) return null
  // 3. positional arguments: kind spellings where a kind is expected; `get deployment web db` = `get deployment/web
  // deployment/db` (reading verbs only; label and annotate take pairs)
  let pos = args.map((a) => (a.glob ? PATTERN + a.v : a.v))
  if (kube) {
    pos = pos.map((a, k) => kindForm(a, k === 0 && KIND_VERBS.has(key)))
    if (NAME_VERBS.has(key) && pos.length > 1 && kindOf(args[0].v) !== null && !args[0].glob && !args[0].v.includes(',') && pos.slice(1).every((o) => !/[/=]/.test(o)))
      pos.splice(0, pos.length, ...pos.slice(1).map((n) => `${pos[0]}/${n}`))
  }
  // options in any order; a repeated (list) option's values in the order given, except KEY=VALUE pairs with distinct
  // keys (`-p A=1 -p B=2`, `--from-literal`), which set independent entries
  const named = [...new Set(opts.map(([n]) => n))].sort().map((n) => {
    const vs = opts.filter(([m]) => m === n).map(([, v]) => v)
    const keys = vs.map((v) => /^([A-Za-z_][\w.-]*)=[^,]*$/.exec(v)?.[1])
    const free = kube && ORDER_FREE.has(n) && keys.every(Boolean) && new Set(keys).size === keys.length
    return `--${n}=${(free ? [...vs].sort() : vs).join('\n')}`
  })
  return [program, `path:${key}`, ...pos, `opts:${named.join('\n')}`, ...tail]
}

/** A comparable form of one command line, or null when only an exact match can accept it. */
function shape(all: Tok[]): string[] | null {
  const program = all[0].v
  if (all[0].quoted || all[0].glob) return null
  if (CLIENTS[program]) return cobraShape(program, all.slice(1))
  const words = all.slice(1)
  const dd = words.findIndex((w) => !w.quoted && w.v === '--')
  const body = dd < 0 ? words : words.slice(0, dd)
  const tail = dd < 0 ? [] : ['--', ...words.slice(dd + 1).map(tailForm)]
  const bools = SHORT_BOOL[program] || ''
  const known = (o: string) => /^-[A-Za-z]$/.test(o) && bools.includes(o[1])
  const optForm = (w: Tok) =>
    !w.quoted && /^-[A-Za-z]{2,}$/.test(w.v) && [...w.v.slice(1)].every((c) => bools.includes(c))
      ? [...w.v.slice(1)].map((c) => `-${c}`)
      : [w.glob ? PATTERN + w.v : w.v]
  // runs of options between operands: reordered only when every option of the run is a known no-value letter
  const out: string[] = [program]
  let run: string[] = []
  const flush = () => {
    if (run.length) out.push(`opts:${(run.every(known) && reorderable(program, run) ? [...run].sort() : run).join(' ')}`)
    run = []
  }
  let valueNext = false // the previous word was an option that may take this word as its value
  for (const w of body) {
    if (isOpt(w)) {
      const parts = optForm(w)
      run.push(...parts)
      valueNext = !parts.every(known)
    } else {
      flush()
      out.push(operandForm(w, PATH_OPERANDS.has(program) && !valueNext, DIR_OPERANDS.has(program) && !valueNext))
      valueNext = false
    }
  }
  flush()
  return [...out, ...tail]
}

/** True when `typed` is the same command as `accepted`, up to the equivalences described above. */
export function equivalentCommand(typed: string, accepted: string): boolean {
  if (normCommand(typed) === normCommand(accepted)) return true
  const a = shellWords(typed)
  const b = shellWords(accepted)
  if (!a || !b || !a.length || !b.length) return false
  const x = shape(a)
  const y = shape(b)
  return !!x && !!y && x.length === y.length && x.every((v, i) => v === y[i])
}
