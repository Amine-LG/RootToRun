import { describe, expect, it } from 'vitest'
import { highlight, highlightJson, highlightYaml, langOf, type Lang, type Tok } from './highlight'
import { configMap, deploymentService, networkPolicy, route } from './highlight.fixtures'

const joined = (rows: Tok[][]) => rows.map((r) => r.map((k) => k.s).join('')).join('\n')
const rowFor = (source: string, text: string) => highlight('yaml', source)[source.split('\n').findIndex((l) => l.includes(text))]
const has = (row: Tok[], c: string, s: string) => expect(row).toContainEqual({ c, s })

describe('manifest grammar scopes', () => {
  it.each([['Deployment + Service', deploymentService], ['ConfigMap', configMap], ['Route', route], ['NetworkPolicy', networkPolicy]])('preserves every byte of %s, including CRLF', (_, source) => {
    for (const code of [source, source.replace(/\n/g, '\r\n')]) {
      const rows = highlight('yaml', code)
      expect(joined(rows)).toBe(code)
      expect(rows.length).toBe(code.split('\n').length)
      expect(rows.flat().some((k) => k.c === 'key')).toBe(true)
    }
  })

  it('distinguishes mapping keys, plain values, numbers and quoted scalars across documents', () => {
    has(rowFor(deploymentService, 'app.kubernetes.io/name'), 'key', 'app.kubernetes.io/name')
    has(rowFor(deploymentService, 'replicas:'), 'num', '3')
    has(rowFor(deploymentService, 'containerPort:'), 'num', '8080')
    has(rowFor(deploymentService, 'value: "8080"'), 'str', '"8080"')
    has(rowFor(deploymentService, "value: 'true'"), 'str', "'true'")
    has(rowFor(deploymentService, 'image:'), 'str', 'quay.io/example/web:1.0')
    has(rowFor(deploymentService, '---'), 'punct', '---')
    has(rowFor(deploymentService, 'kind: Service'), 'key', 'kind')
    has(rowFor(deploymentService, '- name: web'), 'punct', '-')
  })

  it('keeps literal and folded content one string colour until the next sibling', () => {
    for (const text of ['    key: value', '    # this', '    upstream:', '    nested:', '      enabled:', '    still:', '    hello:', '    # also']) {
      const row = rowFor(configMap, text)
      expect(row).toEqual([{ c: 'str', s: configMap.split('\n').find((l) => l.includes(text)) }])
    }
    for (const [key, marker] of [['app.conf', '|-'], ['message', '>+'], ['literal', '|'], ['folded', '>']]) has(rowFor(configMap, `  ${key}:`), 'punct', marker)
    has(rowFor(configMap, '  url:'), 'key', 'url')
    expect(rowFor(configMap, '  url:').filter((k) => k.c === 'com').map((k) => k.s).join('')).toBe('# trailing comment')
  })

  it('recognises quoted keys and protects hashes, escapes and annotation colons', () => {
    has(rowFor(configMap, '"example.com/quoted-key"'), 'key', '"example.com/quoted-key"')
    has(rowFor(configMap, "'example.com/single-key'"), 'key', "'example.com/single-key'")
    has(rowFor(configMap, "'example.com/single-key'"), 'str', "'it''s # a string'")
    has(rowFor(configMap, "'8080':"), 'key', "'8080'")
    has(rowFor(configMap, "'8080':"), 'str', '"0755"')
    has(rowFor(configMap, '  quoted:'), 'str', '"escaped \\"quote\\" # still a string"')
    has(rowFor(deploymentService, 'example.com/description'), 'str', '"web: public # endpoint"')
    has(rowFor(route, 'example.com/endpoint'), 'str', 'https://web.example.test:8443/a#fragment')
    has(rowFor(route, 'haproxy.router'), 'key', 'haproxy.router.openshift.io/timeout')
  })

  it('colours nested mappings, selectors and flow collections in a NetworkPolicy', () => {
    has(rowFor(networkPolicy, '# Only'), 'com', '# Only the frontend can reach the web pods.')
    has(rowFor(networkPolicy, 'policyTypes:'), 'str', 'Ingress')
    has(rowFor(networkPolicy, 'policyTypes:'), 'str', 'Egress')
    has(rowFor(networkPolicy, 'matchLabels: {role:'), 'key', 'role')
    has(rowFor(networkPolicy, 'matchLabels: {role:'), 'str', 'frontend')
    has(rowFor(networkPolicy, 'port: 443'), 'num', '443')
  })

  it('handles anchors, aliases, nested sequences, nulls and numeric-looking strings', () => {
    const source = `defaults: &defaults {enabled: true, empty: null, unset: ~, mode: 0755, port: "8080"}
copy: *defaults
items:
  - - name: nested
      enabled: false
flow: {"quoted/key": "value: # text", 'single': [1, false, null]}
special: {"quoted:key": "colon", 'it''s-key': "apostrophe"}
`
    expect(joined(highlight('yaml', source))).toBe(source)
    const first = rowFor(source, 'defaults:')
    has(first, 'punct', '&defaults')
    for (const s of ['true', 'null', '~']) has(first, 'bool', s)
    has(first, 'num', '0755')
    has(first, 'str', '"8080"')
    has(rowFor(source, 'copy:'), 'punct', '*defaults')
    has(rowFor(source, '- - name:'), 'key', 'name')
    has(rowFor(source, 'enabled: false'), 'bool', 'false')
    has(rowFor(source, 'flow:'), 'key', '"quoted/key"')
    has(rowFor(source, 'flow:'), 'key', "'single'")
    has(rowFor(source, 'flow:'), 'str', '"value: # text"')
    has(rowFor(source, 'special:'), 'key', '"quoted:key"')
    has(rowFor(source, 'special:'), 'key', "'it''s-key'")
  })
})

describe('JSON and fallback', () => {
  it('distinguishes JSON property names, strings, numbers, booleans and null', () => {
    const source = '{\n\t"app.kubernetes.io/name": "web: # public", "port": 8080, "quoted": "8080",\n  "enabled": true, "disabled": false, "empty": null, "ratio": -1.25e+2\n}\n'
    const rows = highlight('json', source)
    expect(joined(rows)).toBe(source)
    has(rows[1], 'key', '"app.kubernetes.io/name"')
    has(rows[1], 'str', '"web: # public"')
    has(rows[1], 'num', '8080')
    has(rows[1], 'str', '"8080"')
    for (const s of ['true', 'false', 'null']) has(rows[2], 'bool', s)
    has(rows[2], 'num', '-1.25e+2')
    expect(highlightJson(source.split('\n'))).toEqual(rows)
    expect(highlightYaml(deploymentService.split('\n'))).toEqual(highlight('yaml', deploymentService))
  })

  it('preserves blanks, trailing whitespace, incomplete input and large input', () => {
    for (const lang of ['yaml', 'json', 'shell', 'plain'] as Lang[]) {
      for (const source of ['', '\n\n', '  \t\n\r\n', 'key: "unfinished # text', '{"key": [', 'x'.repeat(2001), 'x\n'.repeat(25001)])
        expect(joined(highlight(lang, source))).toBe(source)
    }
    expect(highlight('yaml', 'x'.repeat(2001))).toEqual([[{ c: '', s: 'x'.repeat(2001) }]])
  })
})

describe('langOf with captions', () => {
  it('reads the code when the caption names a file of no known kind', () => {
    expect(langOf('sync.template (filled in next)', 'kind: LDAPSyncConfig\napiVersion: v1')).toBe('yaml')
    expect(langOf('glauth.cfg', '[ldap]\n  enabled = true')).toBe('plain')
    expect(langOf('python', 'kind: x')).toBe('plain')
    expect(langOf('deployment.yaml', 'anything')).toBe('yaml')
  })
})
