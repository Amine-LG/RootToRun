// Grammar-based YAML/JSON highlighting, loaded only when a code block needs it. Colours stay in the site's CSS.
import { createHighlighterCoreSync, type HighlighterCore } from 'shiki/core'
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript'
import yaml from 'shiki/langs/yaml.mjs'
import json from 'shiki/langs/json.mjs'
import { canHighlight, highlightShell, plainLines, type Lang, type Tok } from './highlight-shell'

export { highlightShell, langOf, type Lang, type Tok } from './highlight-shell'

let grammar: HighlighterCore | undefined
function highlighter(): HighlighterCore {
  return grammar ??= createHighlighterCoreSync({
    langs: [yaml, json],
    // An empty theme exposes grammar scopes; its colours and font styles are never rendered.
    themes: [{ name: 'scopes', settings: [] }],
    engine: createJavaScriptRegexEngine(),
  })
}

function tokenClass(scopes: string[]): string {
  if (scopes.some((s) => s.startsWith('comment.'))) return 'com'
  if (scopes.includes('entity.name.tag.yaml') || scopes.includes('support.type.property-name.json')) return 'key'
  if (scopes.some((s) => s.startsWith('string.'))) return 'str'
  if (scopes.some((s) => s.startsWith('constant.numeric.'))) return 'num'
  if (scopes.some((s) => /^constant.language\.(boolean|null)\.yaml$/.test(s) || s === 'constant.language.json')) return 'bool'
  if (scopes.some((s) => /^(punctuation\.|keyword\.|storage\.|entity\.other\.document\.|entity\.name\.type\.anchor\.|variable\.other\.alias\.)/.test(s))) return 'punct'
  return ''
}

function merge(tokens: Tok[]): Tok[] {
  const out: Tok[] = []
  for (const token of tokens) {
    if (!token.s) continue
    const prev = out[out.length - 1]
    if (prev?.c === token.c) prev.s += token.s
    else out.push({ ...token })
  }
  return out
}

/** Tokens for display. Large input, grammar errors and unexpected grammar output always fall back to exact text. */
export function highlight(lang: Lang, code: string): Tok[][] {
  const lines = code.split('\n')
  if (!canHighlight(code) || lang === 'plain') return plainLines(lines)
  try {
    if (lang === 'shell') return highlightShell(lines)
    // Shiki normalises line endings. Keep CRLF's CR in its source row when adapting the tokens.
    const source = lines.map((l) => l.replace(/\r$/, '')).join('\n')
    const rows = highlighter().codeToTokensBase(source, { lang, theme: 'scopes', includeExplanation: 'scopeName' }).map((row, i) => {
      const tokens = merge(row.flatMap((token) => token.explanation
        ? token.explanation.map((e) => ({ c: tokenClass(e.scopes.map((s) => s.scopeName)), s: e.content }))
        : [{ c: '', s: token.content }]))
      if (lang === 'yaml') {
        // The YAML grammar scopes quoted keys as strings. A following mapping separator gives them their role.
        for (let j = 0; j < tokens.length; j++) {
          if (!/^(str|num|bool)$/.test(tokens[j].c)) continue
          let next = j + 1
          while (next < tokens.length && !tokens[next].s.trim()) next++
          if (tokens[next]?.c === 'punct' && tokens[next].s.startsWith(':')) tokens[j].c = 'key'
        }
      }
      if (lines[i]?.endsWith('\r')) tokens.push({ c: '', s: '\r' })
      return tokens
    })
    if (rows.length !== lines.length || rows.some((r, i) => r.map((k) => k.s).join('') !== lines[i])) return plainLines(lines)
    return rows
  } catch {
    return plainLines(lines)
  }
}

export const highlightYaml = (lines: string[]): Tok[][] => highlight('yaml', lines.join('\n'))
export const highlightJson = (lines: string[]): Tok[][] => highlight('json', lines.join('\n'))
