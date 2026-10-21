// Writes dist/licenses.txt: the site's own licences and the licence text of every third-party package that can be
// shipped in the built site (the production dependencies in package-lock.json, fonts included). MIT and the SIL Open
// Font License require their notice to travel with the files; the bundler strips it from the code, so it goes here.
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'))
const product = JSON.parse(readFileSync('product.json', 'utf8'))
const rule = '\n' + '-'.repeat(100) + '\n'
const notice = readFileSync('../NOTICE', 'utf8').trim()
const repo = (notice.match(/https:\/\/github\.com\/\S+/) || ['the source repository'])[0]
const out = [
  `${product.name}: licences`,
  '',
  notice,
  rule,
  'Original course content (the lessons, labs, incidents and other text written for the project under content/ in the',
  'source repository): Creative Commons Attribution-ShareAlike 4.0 International, https://creativecommons.org/licenses/by-sa/4.0/',
  'Application code: Apache License 2.0 (full text below).',
  '',
  'Not covered by these licences, and not relicensed by the project: the screenshots of the OpenShift web console',
  '(content/media/; the interface they show belongs to its owners, and the Red Hat and OpenShift names, logos and',
  'artwork in them are trademarks of Red Hat, LLC) and the text printed by third-party programs in the recorded',
  'command outputs, which belongs to its owners.',
  '',
  'Examples adapted from other documentation keep their credit and terms: the OpenShift Container Platform',
  'documentation (Copyright Red Hat, Apache License 2.0, full text below), other Red Hat product documentation',
  '(Copyright Red Hat, CC BY-SA 3.0, https://creativecommons.org/licenses/by-sa/3.0/; the adaptations are licensed',
  'under CC BY-SA 4.0), the Kubernetes documentation (Copyright The Kubernetes Authors, CC BY 4.0,',
  'https://creativecommons.org/licenses/by/4.0/) and a few other projects. Each example is captioned with its source;',
  `the list of examples, source pages and changes is content/ATTRIBUTIONS.md in ${repo}.`,
  'Product names are trademarks of their owners.',
  rule,
  'Apache License 2.0',
  '',
  readFileSync('../LICENSE', 'utf8').trim(),
]

const packages = Object.entries(lock.packages)
  .filter(([path, p]) => path.startsWith('node_modules/') && !p.dev && !p.devOptional)
  .map(([path, p]) => ({ path, name: path.slice(path.lastIndexOf('node_modules/') + 13), version: p.version, license: p.license }))
  .sort((a, b) => a.name.localeCompare(b.name))

// notices a package's own licence file leaves out (checked against the upstream project)
const SUPPLEMENT = {
  '@fontsource-variable/source-serif-4':
    'Copyright notice in the font files: \u00a9 2014 - 2021 Adobe Systems Incorporated (http://www.adobe.com/), with ' +
    'Reserved Font Name \u2018Source\u2019. Upstream notice (adobe-fonts/source-serif, LICENSE.md), not included in the ' +
    'package: Copyright 2014 - 2023 Adobe (http://www.adobe.com/), with Reserved Font Name \u2018Source\u2019. All Rights ' +
    'Reserved. Source is a trademark of Adobe in the United States and/or other countries. The package\u2019s own licence ' +
    'file below names Google Inc.; the copyright holder is Adobe. The font files are the per-script WOFF2 subsets ' +
    'distributed by Google Fonts and packaged by Fontsource, shipped as Fontsource publishes them.\n\n',
}
const missing = []
for (const p of packages) {
  const files = existsSync(p.path) ? readdirSync(p.path).filter((f) => /^(licen[cs]e|copying|notice)(\..*)?$/i.test(f)) : []
  const text = files.map((f) => readFileSync(join(p.path, f), 'utf8').trim()).join('\n\n')
  if (!text) missing.push(p.name)
  out.push(rule + `${p.name} ${p.version} (${p.license || 'see package'})\n\n` + (SUPPLEMENT[p.name] || '') + (text || `Licence: ${p.license}. No licence file is included in the published package.`))
}
writeFileSync('dist/licenses.txt', out.join('\n') + '\n')
console.log(`dist/licenses.txt: ${packages.length} third-party packages`)
// a shipped package without its licence text would be shipped without the notice its licence requires
if (missing.length) {
  console.error(`no licence file in ${missing.length} shipped package(s): ${missing.join(', ')}`)
  process.exit(1)
}
