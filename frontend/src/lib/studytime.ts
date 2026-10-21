// Study-time estimates for a course or a chapter, summed from the authored lesson and lab minutes. They are estimates
// of reading and practice time, rounded so they never look more precise than they are.
import type { Curriculum } from './data'
import { t } from './i18n'
import type { Progress } from './progress'

export interface StudyTime {
  lessons: number // lesson count
  minutes: number // reading and in-browser practice, all lessons
  left: number // minutes of lessons not yet read or skipped
  labs: number // optional lab, incident and challenge count
  labMinutes: number // optional hands-on time on a cluster
}

const finished = (prog: Progress, id: string) => !!(prog.lessons[id]?.done || prog.lessons[id]?.skipped)

/** The time for a set of modules: their lessons, and the labs those lessons or modules point to (counted once). */
export function modulesTime(cur: Curriculum, prog: Progress, moduleIds: string[]): StudyTime {
  const mods = moduleIds.map((m) => cur.modules.find((x) => x.id === m)).filter((m): m is NonNullable<typeof m> => !!m)
  const lessons = mods.flatMap((m) => m.lessons.filter((l) => cur.lessons[l]))
  const labIds = new Set([...lessons.flatMap((l) => cur.lessons[l].labs || []), ...mods.flatMap((m) => m.labs || [])].filter((id) => cur.labs[id]))
  const minutes = lessons.reduce((n, l) => n + (cur.lessons[l].minutes || 0), 0)
  const left = lessons.filter((l) => !finished(prog, l)).reduce((n, l) => n + (cur.lessons[l].minutes || 0), 0)
  const labMinutes = [...labIds].reduce((n, id) => n + (cur.labs[id].minutes || 0), 0)
  return { lessons: lessons.length, minutes, left, labs: labIds.size, labMinutes }
}

export function trackTime(cur: Curriculum, prog: Progress, trackId: string): StudyTime {
  const tr = cur.tracks.find((x) => x.id === trackId)
  return modulesTime(cur, prog, tr ? tr.modules : [])
}

/** "45 min", "about 2 h", "about 7.5 h": minutes below an hour to the nearest 5, hours to the nearest half, written
 * as a plain decimal. Every study-time estimate in the interface goes through here. */
export function duration(min: number, about = true): string {
  if (min <= 0) return t('ui.minutes', { n: 0 })
  if (min < 55) return t('ui.minutes', { n: Math.max(5, Math.round(min / 5) * 5) })
  const h = Math.round(min / 30) / 2
  const s = String(h) // 7.5, 12
  return about ? t('time.aboutH', { h: s }) : t('time.h', { h: s })
}
