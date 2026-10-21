// "Report a problem" and "Edit on GitHub": links to the project's GitHub repository (the backend setting
// ACADEMY_REPO_URL, exposed in meta as repo_url and repo_branch). Without a valid repository nothing is shown.
//
// Edit links open GitHub's editor on the file that defines what is on screen: the YAML file of a lesson, lab,
// incident, challenge, diagnostic, runbook or case (`source`, sent by the backend, which reads it from the files),
// the concept, path and module lists (curriculum `sources`), and the TypeScript of the interactive models and diagrams
// (below). Where no file is known, there is no Edit link, only Report.
// Report links open an issue form of .github/ISSUE_TEMPLATE with fields filled in by their ids (GitHub's issue-form
// query parameters). Only public facts about the page go in: what it is, its title, its relative address and the
// site version; never progress, answers, browser details or the full address with its query.
const enc = encodeURIComponent

export type Contrib = { repo?: string; branch?: string; version?: string }

// exactly https://github.com/<owner>/<repository>: no credentials, other host, query or fragment
export const hasRepo = (m?: Contrib | null) => !!m?.repo && /^https:\/\/github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/.test(m.repo)

/** A repository file on GitHub's edit page; null for a path that could leave the repository. */
export function editUrl(m: Contrib, source: string): string | null {
  const parts = source.split('/')
  if (parts.some((p) => !p || p === '.' || p === '..')) return null
  return `${m.repo}/edit/${enc(m.branch || 'main')}/${parts.map(enc).join('/')}`
}

/** What a page shows. `type` decides the wording, the edit targets and the forms offered. */
export type PageKind = 'lesson' | 'lab' | 'incident' | 'challenge' | 'model' | 'diagram' | 'concept' | 'concepts' | 'runbook' | 'case' | 'diagnostic' | 'path' | 'commands'
export type PageContext = {
  type: PageKind
  id: string // the content id (lesson id, lab id, model id…)
  title: string // what the learner sees as the page's title
  area?: string // where it belongs: the path (territory), "Explore", "Handbook"
  source?: string | null // the YAML file, from the backend (lessons, labs, incidents, challenges, runbooks, cases, diagnostics)
  sources?: Record<string, string | null | undefined> // curriculum sources: concepts, tracks, modules
}

/** The words a form uses for the kind of content (the content-type field and the issue title). */
export const TYPE_LABEL: Record<PageKind, string> = {
  lesson: 'Lesson', lab: 'Guided lab', incident: 'Incident', challenge: 'Challenge', model: 'Interactive model', diagram: 'Diagram',
  concept: 'Concept', concepts: 'Knowledge map', runbook: 'Runbook', case: 'Case study', diagnostic: 'Diagnostic', path: 'Learning path',
  commands: 'Command reference',
}

// The interactive models' code: model id -> its component in frontend/src/sims (checked against sims/index.ts by a test).
export const MODEL_SOURCES: Record<string, string> = {
  scheduler: 'SchedulerSim.tsx', reconcile: 'ReconcileSim.tsx', rollout: 'RolloutSim.tsx', probes: 'ProbesSim.tsx', traffic: 'TrafficSim.tsx',
  rbac: 'RbacSim.tsx', storage: 'StorageSim.tsx', drift: 'DriftSim.tsx', perms: 'PermsSim.tsx',
}
const SIMS_DIR = 'frontend/src/sims/'
export const MODEL_CATALOGUE = 'frontend/src/sims/index.ts' // titles and summaries of the models
export const DIAGRAMS_FILE = 'frontend/src/lib/diagrams.ts' // every diagram, as data

export type EditKey = 'lesson' | 'lab' | 'incident' | 'challenge' | 'runbook' | 'case' | 'diagnostic' | 'modelCode' | 'modelText' | 'diagram' | 'concept' | 'concepts' | 'path' | 'modules'
export type EditTarget = { key: EditKey; path: string; spoiler?: boolean } // key: the wording of the link

/** The files that define what is on screen, the primary one first. Empty: nothing to edit (Report only). */
export function editTargets(c: PageContext): EditTarget[] {
  const one = (key: EditKey, path?: string | null, spoiler?: boolean): EditTarget[] => (path ? [{ key, path, ...(spoiler ? { spoiler } : {}) }] : [])
  switch (c.type) {
    case 'lesson': case 'lab': case 'runbook': case 'case': case 'diagnostic':
      return one(c.type, c.source)
    case 'incident': case 'challenge': // the file holds the answer the page hides until it is asked for
      return one(c.type, c.source, true)
    case 'model':
      return MODEL_SOURCES[c.id] ? [{ key: 'modelCode', path: SIMS_DIR + MODEL_SOURCES[c.id] }, { key: 'modelText', path: MODEL_CATALOGUE }] : []
    case 'diagram':
      return one('diagram', DIAGRAMS_FILE)
    case 'concept': case 'concepts':
      return one(c.type, c.sources?.concepts)
    case 'path':
      return [...one('path', c.sources?.tracks), ...one('modules', c.sources?.modules)]
    default:
      return []
  }
}

/** The issue forms (.github/ISSUE_TEMPLATE) and the fields each one receives. Every field must exist in its form
 *  (tests/test_issue_forms.py reads this table). */
export const FORMS = {
  content: { file: 'content-problem.yml', fields: ['content-type', 'content-id', 'content-title', 'area', 'section', 'page-url', 'site-version'] },
  command: { file: 'incorrect-command.yml', fields: ['content-type', 'content-id', 'content-title', 'area', 'section', 'page-url', 'site-version'] },
  website: { file: 'ui-bug.yml', fields: ['content-type', 'content-id', 'page-url', 'site-version'] },
} as const
export type FormKey = keyof typeof FORMS

/** The forms offered on a page: a mistake in the content, a wrong command (where there are commands), a website defect. */
export function formsFor(type: PageKind | null): FormKey[] {
  if (!type) return ['website']
  return ['lesson', 'lab', 'incident', 'challenge', 'commands'].includes(type) ? ['content', 'command', 'website'] : ['content', 'website']
}

/** Where on the page the reader is, from the address: the #anchor of a section, or a step or stage. Ids only. */
export function sectionOf(hash: string, search: string): string {
  const safe = (s: string | null) => (s && /^[\w.-]{1,100}$/.test(s) ? s : '')
  let h = hash.replace(/^#/, '')
  try {
    h = decodeURIComponent(h)
  } catch {
    h = ''
  }
  if (safe(h)) return h
  const q = new URLSearchParams(search)
  const step = safe(q.get('step')), stage = safe(q.get('stage'))
  return step ? `step ${step}` : stage ? `stage ${stage}` : ''
}

/** A new issue from `form`, with the page's public facts filled in. `path` is the page's address without origin, query
 *  or fragment (anything after ? or # is dropped). */
export function reportUrl(m: Contrib, form: FormKey, c: PageContext | null, path: string, section = ''): string {
  const v: Record<string, string> = {
    'content-type': c ? TYPE_LABEL[c.type] : '',
    'content-id': c?.id || '',
    'content-title': c?.title || '',
    area: c?.area || '',
    section,
    'page-url': path.startsWith('/') && !path.startsWith('//') ? path.split(/[?#]/)[0].replace(/(.)\/+$/, '$1') : '', // the canonical address: no trailing slash
    'site-version': m.version || '',
  }
  const what = c ? `${c.title}: ` : ''
  const title = form === 'website' ? `[Website] ${what}` : `[${c ? TYPE_LABEL[c.type] : 'Content'}] ${what}`
  const q: [string, string][] = [['template', FORMS[form].file], ['title', title], ...FORMS[form].fields.map((f): [string, string] => [f, v[f]])]
  return `${m.repo!.replace(/\/+$/, '')}/issues/new?${q.filter(([, x]) => x).map(([k, x]) => `${k}=${enc(x)}`).join('&')}`
}
