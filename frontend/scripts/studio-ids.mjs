// Writes dist/studio-ids.json so the static export can pre-render one page per Studio item.
// Diagrams and models live in separate namespaces (/studio/diagram/<id>, /studio/model/<id>): an id may exist in both.
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
const paths = []
// Diagram ids are the top-level `id:` of each diagram (4-space indent), not the ids of their nodes.
const sources = [
  ['diagram', 'src/lib/diagrams.ts', /^ {4}id: '([a-z0-9-]+)'/gm],
  ['model', 'src/sims/index.ts', /^ {4}id: '([a-z0-9-]+)'/gm],
]
for (const [kind, f, rx] of sources) {
  if (!existsSync(f)) continue
  for (const m of readFileSync(f, 'utf8').matchAll(rx)) paths.push(`${kind}/${m[1]}`)
}
writeFileSync('dist/studio-ids.json', JSON.stringify(paths))
console.log(`studio pages: ${paths.length}`)
