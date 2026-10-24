import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Md, splitRow } from './md'

const html = (text: string) => renderToStaticMarkup(createElement(Md, { text }))

describe('table rows', () => {
  it('splits on pipes outside code only', () => {
    expect(splitRow('| a | b |')).toEqual(['a', 'b'])
    expect(splitRow('| `a || b` | run b if a fails |')).toEqual(['`a || b`', 'run b if a fails'])
    expect(splitRow('| x \\| y | z |')).toEqual(['x | y', 'z'])
  })
})

describe('tables', () => {
  it('a well-formed table renders header, cells and phone labels as before', () => {
    expect(html('| Command | What it does | Note |\n|---|:---:|---|\n| `oc get pods` | lists **pods** | [docs](https://docs.example/x) |')).toBe(
      '<div class="md "><div class="table-wrap stack-on-phone"><table><thead><tr><th>Command</th><th>What it does</th><th>Note</th></tr></thead>' +
        '<tbody><tr><td data-label="Command"><code class="nb">oc get pods</code></td><td data-label="What it does">lists <strong>pods</strong></td>' +
        '<td data-label="Note"><a href="https://docs.example/x" target="_blank" rel="noreferrer">docs</a></td></tr></tbody></table></div></div>',
    )
    expect(html('| a | b |\n|---|---|\n| 1 | 2 |')).toBe(
      '<div class="md "><div class="table-wrap "><table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td data-label="a">1</td><td data-label="b">2</td></tr></tbody></table></div></div>',
    )
  })
})

describe('malformed tables', () => {
  it('a separator-only table renders without throwing', () => {
    expect(() => html('|---|---|')).not.toThrow()
  })

  it('separator-only lines are skipped and the text around them still renders', () => {
    expect(html('Before.\n\n|---|---|\n|:--:|\n\nAfter.')).toBe('<div class="md "><p>Before.</p><p>After.</p></div>')
  })

  it('a separator first makes the next row the header', () => {
    const out = html('|---|---|\n| a | b |\n| 1 | 2 |')
    expect(out).toContain('<thead><tr><th>a</th><th>b</th></tr></thead>')
    expect(out).toContain('<td data-label="a">1</td><td data-label="b">2</td>')
  })

  it('a header with no separator still renders as a table', () => {
    const out = html('| a | b |\n| 1 | 2 |')
    expect(out).toContain('<th>a</th><th>b</th>')
    expect(out).toContain('<td data-label="b">2</td>')
  })

  it('rows with more or fewer cells than the header keep every cell', () => {
    const out = html('| a | b |\n|---|---|\n| 1 | 2 | 3 |\n| 4 |')
    expect(out).toContain('<td data-label="a">1</td><td data-label="b">2</td><td data-label="">3</td>')
    expect(out).toContain('<tr><td data-label="a">4</td></tr>')
  })

  it('a lone pipe and empty cells render without throwing', () => {
    expect(html('|')).toContain('<th></th>')
    expect(html('| | |\n|---|---|\n| | x |')).toContain('<td data-label=""></td><td data-label="">x</td>')
  })

  it('cells are text, never HTML, and links keep the scheme allow-list', () => {
    const out = html('| <b>x</b> | [y](javascript:alert(1)) |\n|---|---|\n| <img src=x onerror=alert(1)> | z |')
    expect(out).toContain('&lt;b&gt;x&lt;/b&gt;')
    expect(out).toContain('&lt;img src=x onerror=alert(1)&gt;')
    expect(out).not.toContain('<img')
    expect(out).toContain('href="#"')
  })
})
