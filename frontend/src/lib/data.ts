// Data access. Three ways to run the academy, one client:
//   cluster  - the local server with a cluster: content + live labs, Workbench, Explorer
//   practice - the local server without a cluster (ACADEMY_CLUSTER=off): content + recorded outputs
//   static   - no server at all (a public static site): the same JSON, exported to ./data/
// Content never changes between modes; only what can be executed does.

export type Mode = 'REAL_LAB' | 'LOCAL_SIMULATION' | 'GUIDED_INVESTIGATION' | 'ENTERPRISE_ARCHITECTURE' | 'EXTERNAL_LAB_REQUIRED'
export type RunMode = 'cluster' | 'practice' | 'static'
export type Meta = { mode: RunMode; langs: string[]; default_lang: string; helm?: boolean; authoring?: boolean; accounts?: boolean; account_provider?: string; repo_url?: string; repo_branch?: string; version?: string; commit?: string }

export type Track = { id: string; title: string; short?: string; accent?: string; icon?: string; tagline: string; level: string; audience: string; summary: string; outcome: string; modules: string[]; status?: 'available' | 'coming-soon'; roadmap?: string[]; path?: string }
export type Module = { id: string; title: string; summary: string; lessons: string[]; labs?: string[] }
export type LessonSummary = { id: string; title: string; subtitle?: string; module: string; mode: Mode; minutes: number; level: number; concepts: string[]; prerequisites: string[]; labs: string[]; objective: string; checks?: string[]; check_after?: Record<string, string>; path?: string; tools?: string[]; record_on?: 'host' | 'cluster' | 'cluster-admin' }
export type LabSummary = { subtitle?: string; steps?: { id: string; title: string }[]; requires?: string[]; id: string; kind: 'lab' | 'incident' | 'challenge'; title: string; summary: string; module: string; mode: Mode; minutes: number; level: number; concepts: string[]; namespace: string; elevated: boolean; recorded: boolean; recorded_at: string | null; path?: string; tools?: string[] }
export type Concept = { id: string; title: string; module: string; related: string[] }
/** A tool needed to practise outside the website (content/en/tools.yaml; which lessons use it: backend/academy/tools.py) */
export type Tool = { id: string; name: string; what: string; commands: string[]; install: { title: string; url: string }[]; verify: string; notes: string }
/** `path` on a track, lesson, lab or diagnostic: its readable public address (lib/urls.ts) */
export type Curriculum = {
  tracks: Track[]
  modules: Module[]
  lessons: Record<string, LessonSummary>
  concepts: Record<string, Concept>
  labs: Record<string, LabSummary>
  cases: { id: string; title: string; concepts: string[] }[]
  runbooks: { id: string; title: string; when: string }[]
  /** keyed by every track a diagnostic covers; `track` is the diagnostic's own id (URL and saved answers) */
  diagnostics?: Record<string, { track: string; title: string; minutes: number; count: number; path?: string }>
  routes?: Route[]
  /** the files that define the concepts, paths and modules (relative to the repository), for "Edit on GitHub" */
  sources?: { concepts?: string | null; tracks?: string | null; modules?: string | null }
  tools?: Tool[]
}
export type Route = {
  id: string
  title: string
  who: string
  promise: string
  cluster: 'none' | 'optional' | 'recommended'
  begin: { kind: 'lesson' | 'diagnostic' | 'track' | 'lab'; id: string; label: string }
  steps: string[]
}

export type DiagItem = { id: string; targets: string[]; prompt: string; evidence: string; choices: string[]; answer: number; feedback: string[]; explain: string }
export type Diagnostic = { track: string; title: string; intro: string; minutes: number; items: DiagItem[]; source?: string | null }

export type Ref = { title: string; url: string }
export type Predict = {
  prompt: string
  choices: string[]
  answer: number | null
  explain: string
  feedback?: string[]
  /** lessons only: stable question id, role and placement */
  id?: string
  role?: 'check' | 'predict'
  after?: string | null
  answered_by?: string | null
}
/** A lesson written as a teaching flow (see backend curriculum.py: Teach, Show, Try, Ask, Order, Reflect). */
export type FlowChoice = { text: string; why: string }
export type FlowTeach = { kind: 'teach'; id: string; title: string; body: string }
/** "Understand this command" (backend/academy/curriculum.py Understand): every statement checked against `refs` */
export type Understand = { purpose: string; parts: { text: string; means: string }[]; output: string; needs: string; mistakes: string[]; caution: string; concepts: string[]; refs: { title: string; url: string }[] }
/** A real screenshot (backend Screenshot): `url`, `width` and `height` are added by the server from the file. */
export type ScreenshotImage = { src: string; alt: string; captured: string; url: string; width: number; height: number }
export type FlowShow = { kind: 'show'; id: string; title: string; body: string; run: string | null; code: string | null; image?: ScreenshotImage | null; caption: string; origin?: 'file' | 'example' | 'lab'; highlight: string[]; notice: string; understand?: Understand | null }
export type FlowTry = { kind: 'try'; id: string; title: string; body: string; accept: string[]; hints: { match: string; say: string }[]; hint: string; run: string | null; then: string; understand?: Understand | null }
export type FlowAsk = { kind: 'ask'; id: string; prompt: string; evidence: string; choices: FlowChoice[]; answer: number; guess: boolean; explain: string; recalls?: string }
export type FlowOrder = { kind: 'order'; id: string; prompt: string; items: string[]; why: string }
export type FlowReflect = { kind: 'reflect'; id: string; prompt: string; model: string }
export type FlowExplore = { kind: 'explore'; id: string; sim: string | null; diagram: string | null; body: string }
export type FlowStep = FlowTeach | FlowShow | FlowTry | FlowAsk | FlowOrder | FlowReflect | FlowExplore
export type Explain = { prompt: string; audience: string; rubric: string[]; model: string }
export type Card = { q: string; a: string }
export type Lesson = LessonSummary & {
  source?: string | null // the lesson's YAML file, relative to the repository
  supports: string
  sections: { id: string; title: string; body: string; depth?: boolean }[]
  flow?: FlowStep[]
  diagram: string | null
  simulator: string | null
  predict: Predict[]
  explain: Explain[]
  review: Card[]
  limits: string
  enterprise: string
  references: Ref[]
  commands: { cmd: string; meaning: string; expect: 'ok' | 'fail' | 'any' }[]
  files: Record<string, string>
  recording: Recording | null
  host: Record<string, string> | null
  /** only in a language other than English: whether this lesson is translated, stale, or shown in English */
  lang_status?: 'translated' | 'stale' | 'missing'
}

export type Cmd = { cmd: string; meaning: string; run: string | null; stdin: string | null; as: 'learner' | 'reader' | 'admin' | 'host'; expect: 'ok' | 'fail' | 'any'; skip: string; timeout: number }
export type Step = { id: string; title: string; do: string; commands: Cmd[]; predict: Predict | null; observe: string; why: string; checks: string[]; wait_for: string[] }
export type CheckDef = { id: string; title: string; type: string; expect_text: string; final?: boolean; [k: string]: unknown }
export type Lab = LabSummary & {
  supports: string
  prerequisites: string[]
  objective: string
  background: string
  commands: Cmd[]
  extra_namespaces: string[]
  files: Record<string, string>
  setup: string[]
  elevated_setup?: string[] // applied by a cluster administrator into the lab project first (quotas, limits, bindings)
  elevated_why: string
  symptom: string
  requirements?: string[]
  investigate: Cmd[]
  steps: Step[]
  hint_count: number
  checks: CheckDef[]
  symptom_checks?: string[] // incidents: the checks shown before the answer (monitoring-level evidence)
  variations: string[]
  troubleshooting: { problem: string; hint: string }[]
  questions: Card[]
  enterprise: string
  references: Ref[]
  source?: string | null // the lab's YAML file, relative to the repository
}
export type Entry = { step: string; cmd: string; cwd?: string; as: string; identity?: string; expect: string; run: string | null; code: number; stdout: string; stderr: string; combined?: string; ok: boolean; skipped?: string }
export type CheckResult = { id: string; title: string; expect?: string; status: 'pass' | 'fail' | 'error' | 'skip'; observed: string }
export type Verification = { verdict: 'verified' | 'partial' | 'failed' | 'unavailable' | 'not-applicable'; results: CheckResult[] }
export type Trial = { id: string; title: string; kind: 'wrong' | 'partial' | 'alternative'; expect: string; got: string; ok: boolean }
export type Recording = { recorded_at: string; cluster: { kubernetes?: string; oc?: string; openshift?: string; kubectl?: string; distribution?: string }; ok: boolean; entries: Entry[]; verify_before?: Verification; verify_after?: Verification; trials?: Trial[]; experiment?: Experiment | null }
/** An administration lesson's cluster change and the evidence that its rollback restored the cluster. */
export type Experiment = { id: string; restored: boolean; rollback: { cmd: string; code: number }[]; verify: { cmd: string; code: number; ok: boolean }[]; snapshot: { cmd: string; same: boolean }[] }
export type LabData = { lab: Lab; recording: Recording | null }
export type Reveal = { root_cause: string; alternatives: string; sre: string; fix: Cmd[]; fix_recording: Entry[]; verify_after?: Verification; trials?: Trial[] }
export type CommandRef = { cmd: string; meaning: string; lab: string; lab_title: string; kind: string; as: string; run: string | null; stdout: string; stderr: string; code: number | null; tested: boolean; skip: string }
export type ReviewCard = { id: string; q: string; a: string; source: string; ref: string; title: string }
export type RunResult = { refused?: boolean; reason?: string; needs_confirm?: boolean; display?: string; admin?: boolean; code?: number; stdout?: string; stderr?: string; run?: string | null; ok?: boolean }

let runMode: RunMode | null = null
let metaPromise: Promise<Meta> | null = null
const cache = new Map<string, Promise<unknown>>()

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const type = r.headers.get('content-type') || ''
  if (!type.includes('json')) throw new Error(`HTTP ${r.status}`)
  const j = await r.json()
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`)
  return j as T
}

async function detect(): Promise<Meta> {
  try {
    const m = await json<Meta>('/api/meta', { cache: 'no-store' })
    runMode = m.mode
    return m
  } catch {
    const m = await json<Meta>('/data/meta.json', { cache: 'no-cache' })
    runMode = 'static'
    return { ...m, mode: 'static', authoring: false, accounts: false, account_provider: undefined }
  }
}
/** Detects the run mode once; every content request waits for it. */
export const loadMeta = () => (metaPromise ??= detect().catch((e) => ((metaPromise = null), Promise.reject(e))))

export const isStatic = () => runMode === 'static'

function once<T>(key: string, f: () => Promise<T>): Promise<T> {
  if (!cache.has(key)) cache.set(key, f().catch((e) => { cache.delete(key); throw e }))
  return cache.get(key) as Promise<T>
}

// Content: from the server, or from ./data/<lang>/ on a static host.
const content = <T,>(apiPath: string, staticPath: string, lang: string) =>
  once<T>(`${lang}:${apiPath}`, async () => {
    await loadMeta()
    return isStatic() ? json<T>(`/data/${lang}/${staticPath}`) : json<T>(`/api/${apiPath}${apiPath.includes('?') ? '&' : '?'}lang=${lang}`)
  })

export const api = {
  curriculum: (lang: string) => content<Curriculum>('curriculum', 'curriculum.json', lang),
  lesson: (id: string, lang: string) => content<Lesson>(`lessons/${id}`, `lessons/${id}.json`, lang),
  lab: (id: string, lang: string) => content<LabData>(`labs/${id}`, `labs/${id}.json`, lang),
  commands: (lang: string) => content<CommandRef[]>('commands', 'commands.json', lang),
  cards: (lang: string) => content<ReviewCard[]>('cards', 'cards.json', lang),
  caseStudy: (id: string, lang: string) => content<any>(`cases/${id}`, `cases/${id}.json`, lang),
  runbook: (id: string, lang: string) => content<any>(`runbooks/${id}`, `runbooks/${id}.json`, lang),
  diagnostic: (track: string, lang: string) => content<Diagnostic>(`diagnostics/${track}`, `diagnostics/${track}.json`, lang),
  async hints(id: string, n: number, lang: string): Promise<string[]> {
    await loadMeta()
    if (isStatic()) return (await json<{ hints: string[] }>(`/data/${lang}/labs/${id}.hints.json`)).hints.slice(0, n)
    return (await json<{ hints: string[] }>(`/api/labs/${id}/hints?n=${n}&lang=${lang}`)).hints
  },
  async reveal(id: string, lang: string): Promise<Reveal> {
    await loadMeta()
    return isStatic() ? json<Reveal>(`/data/${lang}/labs/${id}.reveal.json`) : post<Reveal>(`/api/labs/${id}/reveal?lang=${lang}`)
  },
}

// Cluster operations (local server with a cluster only).
export async function post<T = any>(url: string, body: unknown = {}): Promise<T> {
  return json<T>(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Academy': '1' }, body: JSON.stringify(body) })
}
export const get = <T = any,>(url: string) => json<T>(url, { cache: 'no-store' })

export type Status = {
  mode: RunMode
  oc: boolean
  crc: { installed: boolean; crcStatus?: string; openshiftStatus?: string; openshiftVersion?: string; ramUsage?: number; ramSize?: number; diskUsage?: number; diskSize?: number }
  identities: Record<'reader' | 'learner' | 'admin', { connected: boolean; user?: string; reason?: string }>
  api: string
  content_errors: string[]
}

export type EnvClass = 'practice' | 'read-only' | 'training'
export type Environment = { class: EnvClass; reason: string; connected?: boolean; api?: string; host?: string; fingerprint?: string; crc?: boolean; tls_verified?: boolean; approved?: { approved_at: number; crc: boolean } }
export type Capabilities = {
  probed: boolean
  user?: string
  kubernetes?: string | null
  apis?: Record<string, boolean | null>
  access?: Record<string, boolean | null>
  storage?: { classes: { name: string; default: boolean; provisioner: string; reclaimPolicy: string; bindingMode: string }[]; default: { name: string; reclaimPolicy: string } | null } | null
  nodes?: number | null
  identities?: Record<string, boolean>
}
export type Preflight = { class: EnvClass; runnable: boolean; requirements: string[]; blockers: { req: string; why: string }[]; unknown?: { req: string; why: string }[]; notes: string[] }
export type LedgerEffect = { id: number; kind: string; name: string; namespace: string | null; scope: string; uid: string | null; identity: string; phase: string; detail: string | null }
export type LedgerVolume = { pv: string; namespace: string; claim: string; phase: string; detail: string | null }
export type CleanupReport = { run: { id: string; lab_id: string; state: string; created_at: number; api: string }; state: string; effects: LedgerEffect[]; volumes: LedgerVolume[]; remaining: number }

export const cluster = {
  status: (lang: string) => get<Status>(`/api/status?lang=${lang}`),
  environment: (probe = false) => get<{ env: Environment; identities: Record<string, { api: string; same_cluster: boolean }>; capabilities?: Capabilities }>(`/api/environment${probe ? '?probe=1' : ''}`),
  approve: (host: string) => post<{ env: Environment }>('/api/environment/approve', { host }),
  revoke: () => post<{ env: Environment }>('/api/environment/revoke'),
  preflight: (id: string) => get<Preflight>(`/api/labs/${id}/preflight`),
  cleanups: () => get<{ runs: CleanupReport[]; leftovers?: { name: string; phase: string; detail: string }[] }>('/api/cleanup'),
  retryCleanup: (runId: string) => post<CleanupReport>(`/api/cleanup/${encodeURIComponent(runId)}`),
  prepare: (id: string, elevated: boolean) => post(`/api/labs/${id}/prepare`, { confirm: true, elevated }),
  verify: (id: string) => post<Verification>(`/api/labs/${id}/verify`),
  check: (id: string, checks: string[]) => post<Verification>(`/api/labs/${id}/check`, { checks }),
  cleanup: (id: string) => post(`/api/labs/${id}/cleanup`, { confirm: true }),
  state: (id: string) => get(`/api/labs/${id}/state`),
  exec: (id: string, where: string, index: number, confirm = false) => post<RunResult>(`/api/labs/${id}/exec`, { where, index, confirm }),
  run: (body: { command: string; identity: string; namespace?: string; confirm?: boolean; stdin?: string; lab_id?: string }) => post<RunResult>('/api/workbench/run', body),
}
