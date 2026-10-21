// @ts-nocheck: uses node modules (child_process, fs) for bash probing; the project has no @types/node
import { describe, expect, it } from 'vitest'
import { commandLines, formatCommand } from './cmdfmt'
import { canonical, contentCommands, hasBash, parses, parsesAll, runs } from './cmdfmt.equiv'
import { highlight, langOf } from './highlight'

// The displayed form of a command (lib/cmdfmt): exact expectations, written from the rule "one top-level command per
// line; a long one continued with ` \`, one pipeline stage per line, then before options", not from the implementation.
const BS = '\\' // one backslash
describe('formatCommand: one command per line', () => {
  const same = (cmd: string) => expect(formatCommand(cmd, 78)).toBe(cmd)
  it('splits a list of commands at the top-level `;`', () => {
    expect(formatCommand('oc get pods; sleep 3; oc get svc', 78)).toBe('oc get pods\nsleep 3\noc get svc')
    expect(formatCommand('a;b ;  c', 78)).toBe('a\nb\nc')
    expect(formatCommand('a;', 78)).toBe('a') // a trailing `;` ends the last command, as the end of the line does
  })
  it('never splits inside quotes, escapes or expansions', () => {
    same("echo 'a;b'")
    same('printf "%s;" a')
    expect(formatCommand('printf "%s;" a; b', 78)).toBe('printf "%s;" a\nb')
    expect(formatCommand(`echo a${BS}; b; c`, 78)).toBe(`echo a${BS}; b\nc`)
    expect(formatCommand(`find . -name x -exec rm {} ${BS}; ; ls`, 78)).toBe(`find . -name x -exec rm {} ${BS};\nls`)
    expect(formatCommand('x=$(a; b); y', 78)).toBe('x=$(a; b)\ny')
    expect(formatCommand('echo `a; b`; c', 78)).toBe('echo `a; b`\nc')
    expect(formatCommand('echo ${x:-a;b}; c', 78)).toBe('echo ${x:-a;b}\nc')
    expect(formatCommand("echo $'a;b'; c", 78)).toBe("echo $'a;b'\nc")
    expect(formatCommand('echo "a $(b; c) d"; e', 78)).toBe('echo "a $(b; c) d"\ne')
    expect(formatCommand('diff <(a; b) <(c); d', 78)).toBe('diff <(a; b) <(c)\nd')
    expect(formatCommand(`sh -c 'trap "exit 0" TERM; sleep 5' ; echo "it's; ok"`, 78)).toBe(`sh -c 'trap "exit 0" TERM; sleep 5'\necho "it's; ok"`)
  })
  it('keeps loops, conditionals, groups and subshells whole', () => {
    same('for i in 1 2; do x; done')
    same('if a; then b; fi')
    same('{ a; b; }')
    same('while true; do sleep 1; done')
    same('until false; do b; done')
    expect(formatCommand('for x in a; do b; done; for y in c; do d; done', 78)).toBe('for x in a; do b; done\nfor y in c; do d; done')
    expect(formatCommand('if a; then b; elif c; then d; else e; fi; f', 78)).toBe('if a; then b; elif c; then d; else e; fi\nf')
    expect(formatCommand('{ a; b; }; c', 78)).toBe('{ a; b; }\nc')
    expect(formatCommand('(cd /tmp; ls); pwd', 78)).toBe('(cd /tmp; ls)\npwd')
    expect(formatCommand('f() { a; b; }; f', 78)).toBe('f() { a; b; }\nf')
    expect(formatCommand('[[ -n $x ]] && echo yes; echo done', 78)).toBe('[[ -n $x ]] && echo yes\necho done')
    expect(formatCommand('a & b; c', 78)).toBe('a & b\nc')
    expect(formatCommand('echo for; echo done', 78)).toBe('echo for\necho done') // reserved words only count as commands
  })
  it('leaves comments, here-documents, case and anything malformed as written', () => {
    expect(formatCommand('a; b # c; d', 78)).toBe('a\nb # c; d')
    for (const c of ['cat <<EOF; x', 'case x in x) a;; esac; b', 'echo "unterminated; b', 'echo done; done', '; a', 'a; ; b',
      'x=$(case y in y) z;; esac); w', 'x=$(a # c); y', 'a\nb; c', `a; b ${BS}`, 'for i in 1 2; do x', 'if a; then b'])
      same(c)
  })
})

// Bash's canonical form (`declare -f`) normalises physical lines away, so it cannot see what depends on them: these
// commands are compared by what bash really prints when it runs them (builtins only, in the sandbox).
describe('formatCommand: commands that depend on the physical lines', () => {
  const cases = [
    `printf '%s\\n' "$LINENO"; printf '%s\\n' "$LINENO"`,
    `printf '%s\\n' "\${LINENO}"; printf '%s\\n' "\${BASH_LINENO[0]:-none}" "$LINENO"`,
    'f() { caller; }; f',
    "set -v; printf '%s\\n' a",
    "printf '%s %s %s %s %s %s\\n' aaaaaaaaaa bbbbbbbbbb cccccccccc dddddddddd eeeeeeeeee \"$LINENO\"; printf x",
  ]
  // not line-sensitive, but an escaped space at the edge of a split: trimmed, the line ends in a backslash (an independent review)
  const escapedEdges = [`printf '<%s>\\n' a${BS} ; printf '<%s>\\n' b`, `printf '<%s>\\n' a; printf '<%s>\\n' b${BS} `,
    `printf '<%s>\\n' a${BS}${BS}${BS}\t; printf x`]
  it.skipIf(!hasBash)('an escaped space next to a `;` is never trimmed away: shown as written, prints what the original prints', () => {
    for (const c of escapedEdges) {
      expect(formatCommand(c, 78)).toBe(c)
      expect(runs(formatCommand(c, 78))).toBe(runs(c))
    }
    expect(runs(escapedEdges[0])).toBe('<a >\n<b>\n|0')
    expect(formatCommand(`printf '<%s>\\n' a${BS}${BS} ; b`, 78)).toBe(`printf '<%s>\\n' a${BS}${BS}\nb`) // an escaped backslash: a plain split
  })
  it.skipIf(!hasBash)('the oracle sees the difference: the same commands on separate lines print something else', () => {
    for (const c of cases.slice(0, 4)) expect(runs(c.replace(/; /, '\n'))).not.toBe(runs(c))
    expect(runs(`printf '%s\\n' a ${BS}\n"$LINENO"\nprintf '%s\\n' "$LINENO"`)).toBe('a\n1\n3\n|0') // a backslash-newline counts too
  })
  it.skipIf(!hasBash)('are shown exactly as written, at every width, and print what the original prints', () => {
    for (const c of cases)
      for (const width of [20, 52, 78]) {
        const shown = formatCommand(c, width)
        expect(shown).toBe(c)
        expect(runs(shown)).toBe(runs(c))
      }
    expect(formatCommand('shopt -s extglob; ls @(a|b)', 78)).toBe('shopt -s extglob; ls @(a|b)') // the option applies to the next line only
  })
})

describe('formatCommand: long commands', () => {
  const long = "oc create deployment web --image=quay.io/example/web:1.0 --replicas=3 --port=8080 -n demo-project --dry-run=client -o yaml | grep -n 'image: x' | tee out.yaml"
  it('leaves short commands alone', () => {
    expect(formatCommand('oc get pods', 78)).toBe('oc get pods')
    expect(formatCommand('cat <<EOF --x --y', 5)).toBe('cat <<EOF --x --y')
  })
  it('puts each pipeline stage on its own line, then continues a long stage before options', () => {
    expect(formatCommand(long, 60)).toBe([
      'oc create deployment web --image=quay.io/example/web:1.0 \\',
      '  --replicas=3 --port=8080 -n demo-project \\',
      '  --dry-run=client -o yaml \\',
      "  | grep -n 'image: x' \\",
      '  | tee out.yaml',
    ].join('\n'))
    for (const ln of formatCommand(long, 60).split('\n')) expect(ln.length).toBeLessThanOrEqual(60)
    expect(formatCommand('podman build -t localhost/app:1 . && podman run --rm localhost/app:1 || echo failed', 40)).toBe(
      'podman build -t localhost/app:1 . \\\n  && podman run --rm localhost/app:1 \\\n  || echo failed')
  })
  it('never splits inside quotes or after a comment', () => {
    const q = `oc get pods -o jsonpath='{.items[0].metadata.name} --not-an-option' --x # a comment --y -z`
    const f = formatCommand(q, 30)
    expect(f).toContain("'{.items[0].metadata.name} --not-an-option'")
    expect(f.split('# a comment')[1]).toBe(' --y -z')
  })
  it('lays out real crowded lesson commands (d.routes-tls, o3.ingress-gateway, ct.podman-stack)', () => {
    const tls = 'oc annotate service web service.beta.openshift.io/serving-cert-secret-name=web-tls; sleep 3; oc get secret web-tls; oc set volume deployment/web --add --name=tls --type=secret --secret-name=web-tls --mount-path=/etc/httpd/tls/localhost.crt --sub-path=tls.crt; oc set volume deployment/web --add --name=tls-key --type=secret --secret-name=web-tls --mount-path=/etc/httpd/tls/localhost.key --sub-path=tls.key; oc rollout status deployment/web --timeout=180s'
    expect(formatCommand(tls, 60)).toBe(`oc annotate service web \\
  service.beta.openshift.io/serving-cert-secret-name=web-tls
sleep 3
oc get secret web-tls
oc set volume deployment/web --add --name=tls \\
  --type=secret --secret-name=web-tls \\
  --mount-path=/etc/httpd/tls/localhost.crt \\
  --sub-path=tls.crt
oc set volume deployment/web --add --name=tls-key \\
  --type=secret --secret-name=web-tls \\
  --mount-path=/etc/httpd/tls/localhost.key \\
  --sub-path=tls.key
oc rollout status deployment/web --timeout=180s`)
    const gw = `host=secure-$(oc project -q).apps-crc.testing; openssl req -x509 -newkey rsa:2048 -nodes -keyout tls.key -out tls.crt -days 2 -subj "/CN=$host" -addext "subjectAltName=DNS:$host" 2>/dev/null; oc create secret tls shop-tls --cert=tls.crt --key=tls.key; sleep 10; oc get routes; sleep 10; curl -sv --cacert tls.crt -o /dev/null https://$host/ 2>&1 | grep -E 'subject:|SSL certificate verify|< HTTP'; curl -s -o /dev/null -D - http://$host/ | grep -i -e '^HTTP' -e '^location'`
    expect(formatCommand(gw, 60)).toBe(`host=secure-$(oc project -q).apps-crc.testing
openssl req -x509 -newkey rsa:2048 -nodes -keyout tls.key \\
  -out tls.crt -days 2 -subj "/CN=$host" \\
  -addext "subjectAltName=DNS:$host" 2>/dev/null
oc create secret tls shop-tls --cert=tls.crt --key=tls.key
sleep 10
oc get routes
sleep 10
curl -sv --cacert tls.crt -o /dev/null https://$host/ 2>&1 \\
  | grep -E 'subject:|SSL certificate verify|< HTTP'
curl -s -o /dev/null -D - http://$host/ \\
  | grep -i -e '^HTTP' -e '^location'`)
    const stack = `podman run -d --name academy-ct3-api --network academy-ct3-net -v academy-ct3-data:/data --secret academy-ct3-token,type=env,target=KV_TOKEN --health-cmd 'wget -qO /dev/null http://localhost:8080/healthz' --health-interval disable quay.io/prometheus/busybox:latest sh -c 'trap "exit 0" TERM; sleep 5; echo "/kv:app:$KV_TOKEN" > /tmp/httpd.conf; httpd -f -p 8080 -h /data -c /tmp/httpd.conf & wait'; podman inspect academy-ct3-api --format 'state={{.State.Status}} health={{.State.Health.Status}}'`
    const lines = formatCommand(stack, 78).split('\n')
    expect(lines[0]).toBe('podman run -d --name academy-ct3-api --network academy-ct3-net \\')
    expect(lines.filter((l) => !l.startsWith('  '))).toEqual([lines[0], 'podman inspect academy-ct3-api \\'])
    expect(lines.at(-1)).toBe("  --format 'state={{.State.Status}} health={{.State.Health.Status}}'")
    expect(lines.some((l) => l.includes(`'trap "exit 0" TERM; sleep 5; echo "/kv:app:$KV_TOKEN" > /tmp/httpd.conf; httpd`))).toBe(true) // the quoted script stays whole
  })
  it('never leaves a command name alone on a line', () => {
    const f = formatCommand("curl -sv https://example.org/ 2>&1 | grep -E 'subject:|SSL certificate verify|< HTTP'", 30)
    expect(f.split('\n')).toContain("  | grep -E 'subject:|SSL certificate verify|< HTTP'")
  })
  it('cuts before other words only when options cannot make a line fit', () => {
    expect(formatCommand('oc label namespace team-a-production-environment pod-security.kubernetes.io/enforce=restricted', 60)).toBe(
      'oc label namespace team-a-production-environment \\\n  pod-security.kubernetes.io/enforce=restricted')
    expect(formatCommand('oc get pods --selector app=web --output wide', 40)).toBe('oc get pods --selector app=web \\\n  --output wide')
    // an option keeps its value on its line, even when the value alone is too long for the box
    expect(formatCommand("podman run --rm busybox sh -c 'echo one; echo two; echo three; echo four'", 30)).toBe(
      "podman run --rm busybox sh \\\n  -c 'echo one; echo two; echo three; echo four'")
  })
  it('marks which lines continue the previous one', () => {
    expect(commandLines('a; b --long-option-one --long-option-two', 24)).toEqual([
      { text: 'a', cont: false },
      { text: 'b --long-option-one', cont: false },
      { text: '  --long-option-two', cont: true },
    ])
  })
  it('never throws or loses characters on odd input', () => {
    for (const c of ['', ';', ';;', BS, "'", '"', '$(', '${', '`', '#', '(((', ')))', '}', 'done', 'a |', '&& b', '{ a', 'a; b; ' + ' '.repeat(200), 'x'.repeat(300), '-'.repeat(100)]) {
      const back = formatCommand(c, 24).replace(/ \\\n */g, ' ').replace(/\n/g, ';').replace(/\s+/g, '')
      expect([c.replace(/\s+/g, ''), c.replace(/\s+/g, '').replace(/;$/, '')]).toContain(back)
    }
  })
})
describe('highlight', () => {
  it('keeps every line exactly', () => {
    const y = 'apiVersion: v1\nkind: Pod # c\nspec:\n  containers:\n  - name: "a b"\n    args: ["x", 1]\n    cmd: |\n      echo: not a key\n  replicas: 3\n'
    for (const lang of ['yaml', 'shell', 'json', 'plain'] as const)
      expect(highlight(lang, y).map((r) => r.map((k) => k.s).join(''))).toEqual(y.split('\n'))
  })
  it('classifies YAML', () => {
    const [k, , lst] = highlight('yaml', 'kind: Pod\nreplicas: 3\n- name: x')
    expect(k.map((x) => x.c)).toEqual(['key', 'punct', '', 'str'])
    expect(highlight('yaml', 'replicas: 3')[0].some((x) => x.c === 'num')).toBe(true)
    expect(lst[0]).toEqual({ c: 'punct', s: '-' })
  })
  it('classifies shell', () => {
    const r = highlight('shell', "oc get pods -n x | grep 'a b' # hi \\")[0]
    expect(r[0]).toEqual({ c: 'bin', s: 'oc' })
    expect(r.find((x) => x.s === '-n')?.c).toBe('opt')
    expect(r.find((x) => x.s === '|')?.c).toBe('punct')
    expect(r.at(-1)?.c).toBe('com')
  })
  it('detects the language', () => {
    expect(langOf('deployment.yaml')).toBe('yaml')
    expect(langOf('', '{"a": 1}')).toBe('json')
    expect(langOf('', '[1, 2]')).toBe('json')
    expect(langOf('', '[\n  {"a": 1}\n]')).toBe('json')
    expect(langOf('', '[learner@workstation ~]$')).toBe('plain') // a prompt, not JSON
    expect(langOf('bash')).toBe('shell')
    expect(langOf('', 'hello world')).toBe('plain')
  })
})


// Every shell string in the content (lesson runs, accepted answers, lab, incident and challenge commands), at three box
// widths: bash must accept the displayed form and read it as the same program as the original. "The same program" is
// what `declare -f` prints for a function wrapping each form: bash's own reading, with comments, spacing,
// backslash-newlines and the `;`/newline choice normalised away, and every word, quote, expansion, redirection and
// operator kept in order.
describe('the displayed form is the same program', () => {
  it.skipIf(!hasBash)('bash tells a different program apart (the check itself works)', () => {
    const [a, b, c, d, e, f] = canonical(['a; b', 'a\nb', "echo 'a;b'", "echo 'a\nb'", 'x --y | z', 'x \\\n  --y \\\n  | z'])
    expect(a).toBe(b)
    expect(c).not.toBe(d)
    expect(e).toBe(f)
    expect(canonical(['a && b'])[0]).not.toBe(canonical(['a\nb'])[0])
    expect(parses('a; b')).toBe(true)
    expect(parses('a; }')).toBe(false)
  })
  it.skipIf(!hasBash)('for every command in content/en', () => {
    const cmds = contentCommands()
    // a command that depends on the physical lines is shown as written (see above); none in content does today
    expect(cmds.filter((c) => /LINENO|\b(caller|shopt)\b|\bset\s+([-+][A-Za-z]*v|[-+]o\s+verbose\b)/.test(c))).toEqual([])
    const pairs: [string, string, number][] = []
    for (const cmd of cmds)
      for (const width of [30, 52, 78]) {
        const shown = formatCommand(cmd, width)
        if (shown !== cmd) pairs.push([cmd, shown, width])
      }
    const ok = parsesAll(pairs.map((p) => p[1]))
    expect(pairs.filter((_, k) => !ok[k]).map((p) => p[1])).toEqual([])
    const before = canonical(pairs.map((p) => p[0]))
    const after = canonical(pairs.map((p) => p[1]))
    const differ = pairs.filter((_, k) => before[k] !== after[k]).map((p) => `${p[2]}: ${p[0]}`)
    expect(differ).toEqual([])
    const split = cmds.filter((c) => formatCommand(c, 1000) !== c)
    console.log(`cmdfmt: ${cmds.length} content commands; ${new Set(pairs.map((p) => p[0])).size} displayed differently at some width (${pairs.length} forms, all read by bash as the original); ${split.length} shown as several commands`)
    expect(cmds.length).toBeGreaterThan(5000)
    expect(split.length).toBeGreaterThan(300)
  }, 600000)
})

describe('robustness (independent review)', () => {
  it('never throws or loses characters on odd input', () => {
    expect(() => highlight('yaml', 'x: |   ')).not.toThrow()
    expect(() => highlight('yaml', 'a: [' + '1,'.repeat(100000) + ']')).not.toThrow()
    expect(highlight('json', '{"a":"unterminated').flat().map((x) => x.s).join('')).toBe('{"a":"unterminated')
    const t0 = Date.now()
    highlight('yaml', 'x' + ' '.repeat(32000))
    expect(Date.now() - t0).toBeLessThan(1000)
  })
})

