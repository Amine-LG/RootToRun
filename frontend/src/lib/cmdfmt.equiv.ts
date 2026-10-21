// @ts-nocheck: test helper; uses node modules (child_process, fs) and the project has no @types/node
// Test helpers for lib/cmdfmt: the shell strings of the course content, and bash's own reading of a script.
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

export const ROOT = resolve(import.meta.dirname, '../../..')

/** Every shell string in content/en: the `cmd`, `run` and `accept` values of lessons, labs, incidents, challenges. */
// the project's virtual environment: .venv/bin/python, or .venv\\Scripts\\python.exe on Windows
export function venvPython(): string {
  return process.platform === 'win32' ? resolve(ROOT, '.venv/Scripts/python.exe') : resolve(ROOT, '.venv/bin/python')
}

export function contentCommands(): string[] {
  const py = `
import sys, json, glob, yaml
out = set()
def walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ('cmd', 'run') and isinstance(v, str): out.add(v)
            elif k == 'accept' and isinstance(v, list): out.update(a for a in v if isinstance(a, str))
            else: walk(v)
    elif isinstance(x, list):
        for v in x: walk(v)
for f in sorted(glob.glob(sys.argv[1] + '/content/en/**/*.yaml', recursive=True)):
    walk(yaml.load(open(f, encoding='utf-8').read(), Loader=yaml.BaseLoader) or [])
print(json.dumps(sorted(out)))
`
  const venv = venvPython()
  const py3 = process.env.ACADEMY_PYTHON || (existsSync(venv) ? venv : 'python3')
  return JSON.parse(execFileSync(py3, ['-I', '-c', py, ROOT], { encoding: 'utf8', maxBuffer: 64 << 20 }))
}

// bash runs with no profile, no PATH and, when bubblewrap is available, a read-only filesystem without network: the
// scripts below only define functions and print them, but a string that escaped its function must not be able to act.
const BWRAP = ['/usr/bin/bwrap', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib64', '/lib64', '--symlink', 'usr/bin', '/bin',
  '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--chdir', '/tmp', '--unshare-all', '--die-with-parent', '--clearenv']
// the equivalence checks need bash itself: on Windows (no /usr/bin/bash) they are skipped and the Linux CI runs them
export const hasBash = existsSync('/usr/bin/bash')
const sandboxed = existsSync('/usr/bin/bwrap') && spawnSync(BWRAP[0], [...BWRAP.slice(1), '/usr/bin/true']).status === 0

function bash(args: string[], script: string) {
  const argv = [...(sandboxed ? BWRAP.slice(1) : []), '/usr/bin/bash', '--noprofile', '--norc', ...args]
  return spawnSync(sandboxed ? BWRAP[0] : argv.shift(), argv, { input: script, encoding: 'utf8', env: { PATH: '/nonexistent', LC_ALL: 'C' }, timeout: 120000, maxBuffer: 256 << 20 })
}

/** Does bash accept the script's syntax? (`bash -n`: read, never run) */
export function parses(script: string): boolean {
  return bash(['-n'], script).status === 0
}

/** `parses` for many scripts: whole batches first, halves only where a batch fails. */
export function parsesAll(scripts: string[]): boolean[] {
  const out: boolean[] = new Array(scripts.length)
  const check = (from: number, to: number) => {
    if (to - from === 1) { out[from] = parses(scripts[from]); return }
    // each script in a function of its own, so that one script cannot end inside another
    if (parses(scripts.slice(from, to).map((s) => `f () {\n${s}\n}\n`).join(''))) { out.fill(true, from, to); return }
    const mid = (from + to) >> 1
    check(from, mid)
    check(mid, to)
  }
  for (let k = 0; k < scripts.length; k += 400) check(k, Math.min(k + 400, scripts.length))
  return out
}

const RS = '\x1e'
/** How bash itself reads each script: the body of a function wrapping it, as `declare -f` prints it back (comments,
 *  backslash-newlines, spacing and the choice between `;` and a newline are normalised away; words, quoting,
 *  expansions, redirections, operators and their order are kept). Scripts must parse (see `parses`). */
export function canonical(scripts: string[]): string[] {
  const out: string[] = []
  for (let k = 0; k < scripts.length; k += 400) {
    const batch = scripts.slice(k, k + 400)
    // the nested function is never called: bash only reads the text
    const src = batch.map((s, j) => `outer_${j} () {\nf () {\n${s}\n}\n}\n`).join('') + batch.map((_, j) => `declare -f outer_${j}; printf '${RS}'\n`).join('')
    const r = bash(['-s'], src)
    if (r.status !== 0) throw new Error(`bash failed: ${r.stderr}`)
    const parts = r.stdout.split(RS)
    parts.pop()
    if (parts.length !== batch.length) throw new Error(`expected ${batch.length} functions, got ${parts.length}`)
    out.push(...parts.map((p) => p.replace(/^outer_\d+ \(\) \n/, '')))
  }
  return out
}

/** What bash prints when it runs `script` (stdout and stderr), in the same sandbox: for the few fixed test scripts
 *  whose meaning only shows when they run (never for content commands). */
export function runs(script: string): string {
  const r = bash(['-s'], script)
  return `${r.stdout}${r.stderr}|${r.status}`
}
