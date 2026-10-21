// Pure DAC teaching model. Sources: path_resolution(7), capabilities(7), inode(7), umask(2),
// and OpenShift 4.21 Creating images → Support arbitrary user ids (linked in PermsSim).
// uid/gid stand for filesystem credentials (normally the effective IDs). No filesystem I/O.
export type FsNode = { path: string; kind: 'dir' | 'file'; uid: number; gid: number; mode: number }
export type ProcessIdentity = { uid: number; gid: number; supplementaryGids: number[]; root: boolean; capabilitiesDropped: boolean }
export type PermissionClass = 'owner' | 'group' | 'other'
export type PermissionBit = 'r' | 'w' | 'x'
export type Operation = 'read' | 'write' | 'execute' | 'list' | 'enter' | 'create' | 'delete'
export type AccessStep = {
  path: string; phase: 'search' | 'operation'; class: PermissionClass; bit: PermissionBit
  bits: string; modeAllows: boolean; allowed: boolean; reason: string
  capability?: 'CAP_DAC_OVERRIDE' | 'CAP_DAC_READ_SEARCH'
}
export type AccessDecision = { allowed: boolean; trace: AccessStep[]; reason: string; error?: 'EACCES' | 'ENOENT' | 'ENOTDIR' | 'EISDIR' | 'EEXIST'; created?: FsNode }

export const DATA_PATH = '/opt/app/data'
export const FILE_PATH = `${DATA_PATH}/state.db`
export const OPERATIONS: { value: Operation; label: string }[] = [
  { value: 'read', label: 'Read file (r)' }, { value: 'write', label: 'Write file (w)' },
  { value: 'execute', label: 'Execute file (x)' }, { value: 'list', label: 'List directory names (r)' },
  { value: 'enter', label: 'Enter / traverse directory (x)' },
  { value: 'create', label: 'Create new.txt in directory (w+x)' }, { value: 'delete', label: 'Delete state.db (parent w+x)' },
]

/** Only the nine rwx bits and, on directories, setgid. No silent truncation or partial parsing. */
export function parseMode(text: string, directory = false): number | null {
  if (!(directory ? /^[02]?[0-7]{3}$/ : /^0?[0-7]{3}$/).test(text)) return null
  return parseInt(text, 8)
}
export function parseId(text: string): number | null {
  if (!/^\d+$/.test(text)) return null
  const n = Number(text)
  return Number.isInteger(n) && n <= 4294967294 ? n : null
}
export function parseGids(text: string): number[] | null {
  if (!text.trim()) return []
  const values = text.trim().split(/[\s,]+/).map(parseId)
  return values.some((n) => n === null) ? null : [...new Set(values as number[])]
}
export const octalMode = (mode: number): string => mode.toString(8).padStart(3, '0')
export function rwx(bits: number): string {
  return `${bits & 4 ? 'r' : '-'}${bits & 2 ? 'w' : '-'}${bits & 1 ? 'x' : '-'}`
}
export function symbolicMode(node: FsNode): string {
  const group = rwx((node.mode >> 3) & 7)
  return `${node.kind === 'dir' ? 'd' : '-'}${rwx((node.mode >> 6) & 7)}${group.slice(0, 2)}${node.kind === 'dir' && node.mode & 0o2000 ? (node.mode & 0o010 ? 's' : 'S') : group[2]}${rwx(node.mode & 7)}`
}
export const lsLine = (node: FsNode): string => `${symbolicMode(node)} ${node.uid} ${node.gid} ${node.path}`
export const idLine = (p: ProcessIdentity): string => `uid=${p.uid} gid=${p.gid} groups=${[...new Set([p.gid, ...p.supplementaryGids])].join(',')}`

/** Select exactly one class. A matching owner never falls back to group or other. */
export function permissionClass(node: FsNode, p: ProcessIdentity): PermissionClass {
  return p.uid === node.uid ? 'owner' : p.gid === node.gid || p.supplementaryGids.includes(node.gid) ? 'group' : 'other'
}

export function checkBit(node: FsNode, p: ProcessIdentity, bit: PermissionBit, phase: AccessStep['phase'] = 'operation'): AccessStep {
  const selected = permissionClass(node, p)
  const bits = (node.mode >> ({ owner: 6, group: 3, other: 0 }[selected])) & 7
  const modeAllows = !!(bits & { r: 4, w: 2, x: 1 }[bit])
  let capability: AccessStep['capability']
  // This model couples the two DAC capabilities to root, unless dropped. Real capabilities are per-thread
  // and can be held separately, including by nonzero UIDs. Directory search has no "any x bit" restriction.
  if (!modeAllows && p.uid === 0 && p.root && !p.capabilitiesDropped) {
    if (bit === 'r' || (node.kind === 'dir' && bit === 'x')) capability = 'CAP_DAC_READ_SEARCH'
    else if (bit !== 'x' || node.kind === 'dir' || (node.mode & 0o111) !== 0) capability = 'CAP_DAC_OVERRIDE'
  }
  const allowed = modeAllows || !!capability
  const whyClass = selected === 'owner' ? `UID ${p.uid} matches owner; only owner bits count` : selected === 'group' ? `GID ${node.gid} matches the primary or a supplementary group; only group bits count` : 'No owner or group match; only other bits count'
  const reason = `${whyClass}. ${bit} ${modeAllows ? 'is set' : 'is absent'} in ${rwx(bits)}.${capability ? ` ${capability} bypasses this DAC check.` : !allowed && bit === 'x' && node.kind === 'file' && p.uid === 0 && p.root && !p.capabilitiesDropped && !(node.mode & 0o111) ? ' CAP_DAC_OVERRIDE cannot execute a file with no x bits in any class.' : ''}`
  return { path: node.path, phase, class: selected, bit, bits: rwx(bits), modeAllows, allowed, reason, ...(capability ? { capability } : {}) }
}

/** Regular-file creation: setgid parent supplies the GID, umask removes bits from the requested mode. */
export function createdFile(parent: FsNode, p: ProcessIdentity, umask: number, requestedMode = 0o666): FsNode {
  return { path: `${parent.path === '/' ? '' : parent.path}/new.txt`, kind: 'file', uid: p.uid, gid: parent.mode & 0o2000 ? parent.gid : p.gid, mode: requestedMode & ~umask & 0o777 }
}

/** Resolve an absolute path, stopping at the first failed search or operation bit. No state is mutated.
 * create targets a directory; delete targets an existing file and checks its parent, not the file's mode.
 */
export function evaluateAccess(nodes: readonly FsNode[], p: ProcessIdentity, operation: Operation, target: string, umask = 0o022, requestedMode = 0o666): AccessDecision {
  const trace: AccessStep[] = []
  const fail = (error: NonNullable<AccessDecision['error']>, reason: string): AccessDecision => ({ allowed: false, trace, error, reason })
  if (!target.startsWith('/') || target.includes('//') || target.split('/').some((s) => s === '.' || s === '..') || (target !== '/' && target.endsWith('/'))) throw new Error('Use a canonical absolute path.')
  const parts = target.split('/').filter(Boolean)
  const paths = ['/', ...parts.map((_, i) => '/' + parts.slice(0, i + 1).join('/'))]
  const check = (node: FsNode, bit: PermissionBit, phase: AccessStep['phase']): boolean => {
    const step = checkBit(node, p, bit, phase)
    trace.push(step)
    return step.allowed
  }
  let leaf: FsNode | undefined
  for (let i = 0; i < paths.length; i++) {
    const node = nodes.find((n) => n.path === paths[i])
    if (!node) return fail('ENOENT', `${paths[i]} does not exist.`)
    if (i < paths.length - 1) {
      if (node.kind !== 'dir') return fail('ENOTDIR', `${node.path} is not a directory.`)
      if (!check(node, 'x', 'search')) return fail('EACCES', `Cannot search ${node.path}; later nodes are not reached.`)
    }
    leaf = node
  }
  const node = leaf!
  const fileOp = operation === 'read' || operation === 'write' || operation === 'execute' || operation === 'delete'
  if (fileOp && node.kind !== 'file') return fail('EISDIR', `${target} is a directory; choose a file for this operation.`)
  if (!fileOp && node.kind !== 'dir') return fail('ENOTDIR', `${target} is not a directory.`)
  // Creating target/new.txt must search target to look up the new entry, before checking parent write.
  if (operation === 'create' && !check(node, 'x', 'search')) return fail('EACCES', `Cannot search ${target} to look up new.txt.`)
  const subject = operation === 'delete' ? nodes.find((n) => n.path === paths[paths.length - 2])! : node
  const required: PermissionBit[] = operation === 'create' || operation === 'delete' ? ['w', 'x'] : [operation === 'read' || operation === 'list' ? 'r' : operation === 'write' ? 'w' : 'x']
  for (const bit of required) if (!check(subject, bit, 'operation')) return fail('EACCES', `${subject.path} lacks ${bit} for ${operation}.`)
  if (operation === 'create') {
    const created = createdFile(node, p, umask, requestedMode)
    if (nodes.some((n) => n.path === created.path)) return fail('EEXIST', `${created.path} already exists.`)
    return { allowed: true, trace, reason: 'Parent w+x permits creation. The new file gets its own owner, group and mode.', created }
  }
  return { allowed: true, trace, reason: operation === 'delete' ? 'Parent w+x permits unlinking the file. The file’s own rwx bits do not control deletion here.' : operation === 'list' ? 'Directory r permits listing names. Looking up a child or reading its metadata also needs directory x.' : 'All ancestor search checks and the requested operation bit passed.' }
}

export type PermsPreset = { id: string; label: string; note: string; nodes: FsNode[]; process: ProcessIdentity; operation: Operation; target: string; umask: number }
const imageNodes = (): FsNode[] => [
  { path: '/', kind: 'dir', uid: 0, gid: 0, mode: 0o755 },
  { path: '/opt', kind: 'dir', uid: 0, gid: 0, mode: 0o755 },
  ...['/opt/app', DATA_PATH, FILE_PATH].map((path): FsNode => ({ path, kind: path === FILE_PATH ? 'file' : 'dir', uid: 1001, gid: 1001, mode: 0o755 })),
]
const process = (uid: number, gid: number, supplementaryGids: number[] = [], capabilitiesDropped = false): ProcessIdentity => ({ uid, gid, supplementaryGids, root: uid === 0, capabilitiesDropped })
const fixedNodes = () => imageNodes().map((n) => n.path.startsWith('/opt/app') ? { ...n, gid: 0, mode: (n.mode & ~0o070) | (((n.mode >> 6) & 7) << 3) } : n)
export function permsPresets(): PermsPreset[] {
  const base = { operation: 'write' as Operation, target: FILE_PATH, umask: 0o022 }
  return [
    { ...base, id: 'image', label: 'Image built as UID 1001 (chown 1001, mode 755)', note: 'The app tree belongs to 1001:1001 with mode 755. Its owner can write.', nodes: imageNodes(), process: process(1001, 1001) },
    { ...base, id: 'openshift', label: 'Same image run by OpenShift: UID 1000680000, GID 0', note: 'OpenShift assigns an arbitrary UID; the container user is a member of the root group. This example uses primary GID 0. GID 0 grants no root capabilities.', nodes: imageNodes(), process: process(1000680000, 0) },
    { ...base, id: 'fixed', label: 'Fixed image: chgrp -R 0 && chmod -R g=u', note: 'Applied to /opt/app only: copy owner permissions to group 0 (755 → 775). Group write permits writing existing files; group w+x on directories permits creation and deletion.', nodes: fixedNodes(), process: process(1000680000, 0) },
    { ...base, id: 'root', label: 'Root in a container', note: 'Here UID 0 retains both DAC capabilities. Container policies may drop them; root alone is not a guarantee of bypass.', nodes: imageNodes(), process: process(0, 0) },
    { ...base, id: 'root-dropped', label: 'Root with capabilities dropped', note: 'UID 0 has no DAC bypass here. It must pass the same owner/group/other checks as any process.', nodes: imageNodes(), process: process(0, 0, [], true) },
    { ...base, id: 'umask', label: 'umask 077 surprise', operation: 'read', note: 'A previous UID 1001 process created state.db with requested mode 666 and umask 077: mode 600, group 0. The next arbitrary UID cannot read it. Umask affects creation, not existing files.', nodes: fixedNodes().map((n) => n.kind === 'file' ? { ...n, mode: 0o666 & ~0o077 } : n), process: process(1000680000, 0), umask: 0o077 },
    { ...base, id: 'setgid', label: 'Setgid shared directory', operation: 'create', target: DATA_PATH, umask: 0o002, note: 'data is 2770 with group 2000. Supplementary group 2000 permits creation; setgid makes new.txt inherit GID 2000 instead of primary GID 1002. Umask 002 leaves mode 664.', nodes: imageNodes().map((n) => n.path === DATA_PATH ? { ...n, gid: 2000, mode: 0o2770 } : n), process: process(1002, 1002, [2000]) },
  ]
}
