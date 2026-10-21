// What the learner has actually done for a concept, as separate facts. One place derives this for every page
// (map, profile, path), so two pages can never disagree. Reading, checking, practising and verifying are different
// kinds of evidence and are never added together into a single "understood" percentage. Questions and activities are
// read by the shared rules in lib/standing.ts.
import type { Curriculum } from './data'
import { labStatus, type Progress } from './progress'
import { checksOf, tallyActivities, tallyChecks } from './standing'

export type ConceptEvidence = {
  /** lessons teaching this concept that the learner finished reading */
  read: number
  lessons: number
  /** questions about this concept: answered at least once, right on the latest attempt (of which corrected after
   *  the answer was shown) */
  checksAnswered: number
  checksCorrect: number
  checksCorrected: number
  checks: number
  /** labs, incidents and challenges about this concept: completed (lib/standing.ts activityDone), and verified on a
   *  cluster by the latest verdict */
  practised: number
  verified: number
  labs: number
  /** activities with anything on record (opened a step, a hint, the answer shown): work in progress is listed too */
  begun: number
  /** where the concept is taught and practised, in the order of the course: what a page links to */
  lessonIds: string[]
  labIds: string[]
}

export type EvidenceLevel = 'none' | 'read' | 'checked' | 'practised' | 'verified'

/** Modules in the order of the course: the tracks' modules in order, then any module no track lists. */
export function moduleOrder(cur: Curriculum): string[] {
  return [...new Set([...cur.tracks.flatMap((tr) => tr.modules), ...cur.modules.map((m) => m.id)])]
}

/** Lessons in the order of the course (by module, then any lesson no module lists). */
export function courseOrder(cur: Curriculum): string[] {
  const listed = moduleOrder(cur).flatMap((id) => cur.modules.find((m) => m.id === id)?.lessons || []).filter((l) => cur.lessons[l])
  return [...new Set([...listed, ...Object.keys(cur.lessons)])]
}

export function conceptEvidence(cur: Curriculum, prog: Progress, conceptId: string): ConceptEvidence {
  const lessonIds = courseOrder(cur).filter((l) => cur.lessons[l].concepts.includes(conceptId))
  const modules = new Map(moduleOrder(cur).map((m, i) => [m, i]))
  const labIds = Object.values(cur.labs)
    .filter((l) => l.concepts.includes(conceptId))
    .sort((a, b) => (modules.get(a.module) ?? 999) - (modules.get(b.module) ?? 999) || a.level - b.level)
    .map((l) => l.id)
  const q = tallyChecks(checksOf(cur, lessonIds), prog)
  const a = tallyActivities(cur, labIds, prog)
  return {
    read: lessonIds.filter((l) => prog.lessons[l]?.done).length, // skipping the reading is not reading
    lessons: lessonIds.length,
    checksAnswered: q.answered,
    checksCorrect: q.right,
    checksCorrected: q.corrected,
    checks: q.total,
    practised: a.done,
    verified: a.verified,
    labs: a.total,
    begun: labIds.filter((l) => labStatus(prog.labs[l]) !== 'new').length,
    lessonIds,
    labIds,
  }
}

/** The strongest kind of evidence present, for a compact marker (map node, path row). */
export function evidenceLevel(e: ConceptEvidence): EvidenceLevel {
  if (e.verified) return 'verified'
  if (e.practised) return 'practised'
  if (e.checksCorrect) return 'checked'
  if (e.read) return 'read'
  return 'none'
}
