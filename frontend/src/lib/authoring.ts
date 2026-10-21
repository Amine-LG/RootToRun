/** Pure helpers shared by the local editor and its tests. */
export type AuthorKind = 'lesson' | 'module' | 'track' | 'route' | 'diagnostic'
export type AuthorEntry = { kind: AuthorKind; id: string; title: string; file: string }
export type AuthorItem = AuthorEntry & { yaml: string; hash: string }
export type AuthorDraft = { kind: AuthorKind; id: string; file: string; yaml: string; base_hash: string; saved_at: string }
export type Problems = { ok: boolean; errors: string[]; warnings: string[] }
export type Revision = { revision: string; yaml: string }

export function tokenFromFragment(hash: string, stored: string | null): { token: string; consumed: boolean } {
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  return { token: params.get('token') || stored || '', consumed: params.has('token') }
}

export function filterEntries(entries: AuthorEntry[], query: string): AuthorEntry[] {
  const words = query.trim().toLocaleLowerCase().split(/\s+/)
  return entries.filter(entry => words.every(word => `${entry.kind} ${entry.id} ${entry.title} ${entry.file}`.toLocaleLowerCase().includes(word)))
}

export function formatApiError(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'errors' in detail && Array.isArray(detail.errors)) return detail.errors.join('\n')
  return JSON.stringify(detail)
}
