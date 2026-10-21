import { describe, expect, it } from 'vitest'
import {
  DATA_PATH, FILE_PATH, checkBit, createdFile, evaluateAccess, idLine, lsLine, octalMode, parseGids,
  parseId, parseMode, permissionClass, permsPresets, rwx, symbolicMode,
  type FsNode, type Operation, type PermissionBit, type ProcessIdentity,
} from './perms'

const who = (patch: Partial<ProcessIdentity> = {}): ProcessIdentity => ({ uid: 1001, gid: 1001, supplementaryGids: [], root: false, capabilitiesDropped: false, ...patch })
const file = (mode = 0o755): FsNode => ({ path: FILE_PATH, kind: 'file', uid: 1001, gid: 2000, mode })
const preset = (id: string) => permsPresets().find((p) => p.id === id)!
const tree = (changes: Record<string, Partial<FsNode>> = {}) => preset('image').nodes.map((n) => ({ ...n, ...changes[n.path] }))
const last = <T,>(items: T[]) => items[items.length - 1]

describe('permission classes and individual bits (path_resolution(7))', () => {
  it('uses owner only even if the process also matches the group and group/other allow everything', () => {
    const n = file(0o077), p = who({ gid: 2000 })
    expect(permissionClass(n, p)).toBe('owner')
    for (const bit of ['r', 'w', 'x'] as PermissionBit[]) expect(checkBit(n, p, bit)).toMatchObject({ class: 'owner', allowed: false, modeAllows: false, bits: '---' })
  })

  it('uses group only on a primary or supplementary match, without falling back to other', () => {
    const n = file(0o707)
    for (const p of [who({ uid: 1002, gid: 2000 }), who({ uid: 1002, supplementaryGids: [3000, 2000] })]) {
      expect(permissionClass(n, p)).toBe('group')
      expect(checkBit(n, p, 'r').allowed).toBe(false)
    }
    expect(permissionClass(n, who({ uid: 1002 }))).toBe('other')
    expect(checkBit(n, who({ uid: 1002 }), 'r').allowed).toBe(true)
  })

  it('checks all 512 modes against each class and all three bits, independently of the unused classes', () => {
    const cases = [
      { p: who({ gid: 2000 }), class: 'owner', divisor: 64 },
      { p: who({ uid: 1002, gid: 2000 }), class: 'group', divisor: 8 },
      { p: who({ uid: 1002, supplementaryGids: [2000] }), class: 'group', divisor: 8 },
      { p: who({ uid: 1002 }), class: 'other', divisor: 1 },
    ]
    for (let mode = 0; mode <= 0o777; mode++) for (const c of cases) for (const [bit, value] of [['r', 4], ['w', 2], ['x', 1]] as const) {
      const bits = Math.floor(mode / c.divisor) % 8
      expect(checkBit(file(mode), c.p, bit)).toMatchObject({ class: c.class, allowed: Math.floor(bits / value) % 2 === 1 })
    }
  })
})

describe('path walk and operation requirements', () => {
  it('traces search on every ancestor including /, then the requested file bit', () => {
    const r = evaluateAccess(tree(), who(), 'write', FILE_PATH)
    expect(r.allowed).toBe(true)
    expect(r.trace.map((s) => [s.path, s.phase, s.class, s.bit, s.allowed])).toEqual([
      ['/', 'search', 'other', 'x', true], ['/opt', 'search', 'other', 'x', true],
      ['/opt/app', 'search', 'owner', 'x', true], [DATA_PATH, 'search', 'owner', 'x', true],
      [FILE_PATH, 'operation', 'owner', 'w', true],
    ])
  })

  it('stops at any unsearchable ancestor even when the file is world readable/writable/executable', () => {
    for (const path of ['/', '/opt', '/opt/app', DATA_PATH]) {
      const nodes = tree({ [path]: { mode: 0o666 }, [FILE_PATH]: { mode: 0o777 } })
      for (const op of ['read', 'write', 'execute'] as Operation[]) {
        const r = evaluateAccess(nodes, who(), op, FILE_PATH)
        expect(r).toMatchObject({ allowed: false, error: 'EACCES' })
        expect(last(r.trace)).toMatchObject({ path, bit: 'x', allowed: false })
        expect(r.trace.some((s) => s.path === FILE_PATH)).toBe(false)
      }
    }
  })

  it('needs search, not read, on ancestors', () => {
    const nodes = tree(Object.fromEntries(['/', '/opt', '/opt/app', DATA_PATH].map((path) => [path, { mode: 0o111 }])))
    expect(evaluateAccess(nodes, who(), 'read', FILE_PATH).allowed).toBe(true)
  })

  it('separates directory names (r) from entry/search (x) and reading a child', () => {
    const readOnly = tree({ [DATA_PATH]: { mode: 0o400 } })
    expect(evaluateAccess(readOnly, who(), 'list', DATA_PATH).allowed).toBe(true)
    expect(evaluateAccess(readOnly, who(), 'enter', DATA_PATH).allowed).toBe(false)
    expect(evaluateAccess(readOnly, who(), 'read', FILE_PATH).allowed).toBe(false)
    const searchOnly = tree({ [DATA_PATH]: { mode: 0o100 } })
    expect(evaluateAccess(searchOnly, who(), 'enter', DATA_PATH).allowed).toBe(true)
    expect(evaluateAccess(searchOnly, who(), 'list', DATA_PATH).allowed).toBe(false)
    expect(evaluateAccess(searchOnly, who(), 'read', FILE_PATH).allowed).toBe(true)
  })

  it('uses only the requested bit on a file: write does not imply read or execute', () => {
    const nodes = tree({ [FILE_PATH]: { mode: 0o200 } })
    expect(evaluateAccess(nodes, who(), 'write', FILE_PATH).allowed).toBe(true)
    expect(evaluateAccess(nodes, who(), 'read', FILE_PATH).allowed).toBe(false)
    expect(evaluateAccess(nodes, who(), 'execute', FILE_PATH).allowed).toBe(false)
  })

  it('requires parent w+x for create and delete; neither needs directory r or any file permission', () => {
    for (const mode of [0o000, 0o100, 0o200, 0o300, 0o700]) {
      const nodes = tree({ [DATA_PATH]: { mode }, [FILE_PATH]: { mode: 0o000 } })
      for (const op of ['create', 'delete'] as const) {
        const r = evaluateAccess(nodes, who(), op, op === 'create' ? DATA_PATH : FILE_PATH)
        expect(r.allowed).toBe(mode === 0o300 || mode === 0o700)
        expect(r.trace.every((s) => s.path !== FILE_PATH)).toBe(true)
      }
    }
  })

  it('file write needs no parent write, while deletion of a writable file still needs parent write', () => {
    const nodes = tree({ [DATA_PATH]: { mode: 0o500 }, [FILE_PATH]: { mode: 0o600 } })
    expect(evaluateAccess(nodes, who(), 'write', FILE_PATH).allowed).toBe(true)
    expect(evaluateAccess(nodes, who(), 'delete', FILE_PATH).allowed).toBe(false)
    expect(evaluateAccess(nodes, who(), 'create', DATA_PATH).allowed).toBe(false)
  })

  it('creation searches the parent for the new entry before checking parent write', () => {
    const r = evaluateAccess(tree({ [DATA_PATH]: { mode: 0o200 } }), who(), 'create', DATA_PATH)
    expect(last(r.trace)).toMatchObject({ path: DATA_PATH, phase: 'search', bit: 'x', allowed: false })
    expect(r.trace.every((s) => s.phase === 'search')).toBe(true)
  })

  it('directory operations also search ancestors, and / itself has no ancestors', () => {
    for (const op of ['list', 'enter', 'create'] as Operation[]) {
      expect(evaluateAccess(tree({ '/opt/app': { mode: 0o000 } }), who(), op, DATA_PATH).error).toBe('EACCES')
    }
    const r = evaluateAccess(tree(), who(), 'list', '/')
    expect(r.trace).toHaveLength(1)
    expect(r.trace[0]).toMatchObject({ phase: 'operation', path: '/', bit: 'r' })
  })

  it('reports missing paths, non-directories, wrong operation targets and creation collisions', () => {
    expect(evaluateAccess(tree(), who(), 'read', `${DATA_PATH}/missing`).error).toBe('ENOENT')
    expect(evaluateAccess(tree({ '/opt/app': { kind: 'file' } }), who(), 'read', FILE_PATH).error).toBe('ENOTDIR')
    expect(evaluateAccess(tree(), who(), 'read', DATA_PATH).error).toBe('EISDIR')
    expect(evaluateAccess(tree(), who(), 'list', FILE_PATH).error).toBe('ENOTDIR')
    const nodes = [...tree(), { ...file(), path: `${DATA_PATH}/new.txt` }]
    expect(evaluateAccess(nodes, who(), 'create', DATA_PATH).error).toBe('EEXIST')
    expect(evaluateAccess(tree({ '/opt': { mode: 0 } }), who(), 'read', '/opt/missing').error).toBe('EACCES')
    for (const path of ['opt/app', '/opt//app', '/opt/../app', '/opt/./app', '/opt/']) expect(() => evaluateAccess(tree(), who(), 'list', path)).toThrow('canonical absolute path')
  })
})

describe('root bypass comes from DAC capabilities', () => {
  const root = who({ uid: 0, gid: 0, root: true })
  it('bypasses file r/w and directory r/w/search with no bits set', () => {
    const nodes = tree(Object.fromEntries(tree().map((n) => [n.path, { mode: 0 }])))
    for (const op of ['read', 'write', 'list', 'enter', 'create', 'delete'] as Operation[]) {
      const directoryOp = ['list', 'enter', 'create'].includes(op)
      const r = evaluateAccess(nodes, root, op, directoryOp ? DATA_PATH : FILE_PATH)
      expect(r.allowed).toBe(true)
      expect(r.trace.every((s) => s.capability && !s.modeAllows)).toBe(true)
    }
    expect(checkBit(file(0), root, 'r').capability).toBe('CAP_DAC_READ_SEARCH')
    expect(checkBit(file(0), root, 'w').capability).toBe('CAP_DAC_OVERRIDE')
  })

  it('file execution needs at least one x bit in any class, including when root owns it', () => {
    for (const mode of [0o000, 0o666, 0o100, 0o010, 0o001]) {
      for (const uid of [0, 1001]) {
        const r = checkBit({ ...file(mode), uid }, root, 'x')
        expect(r.allowed).toBe(!!(mode & 0o111))
        if (!r.allowed) expect(r.reason).toContain('no x bits')
      }
    }
    expect(evaluateAccess(tree({ [FILE_PATH]: { mode: 0o600 } }), root, 'execute', FILE_PATH).allowed).toBe(false)
  })

  it('dropped capabilities disable every bypass, but ordinary bits can still grant access', () => {
    const dropped = { ...root, capabilitiesDropped: true }
    for (const bit of ['r', 'w', 'x'] as PermissionBit[]) expect(checkBit(file(0), dropped, bit).allowed).toBe(false)
    expect(checkBit(file(0o007), dropped, 'w')).toMatchObject({ allowed: true, modeAllows: true })
    expect(evaluateAccess(tree(), dropped, 'write', FILE_PATH).allowed).toBe(false)
    expect(evaluateAccess(tree(), dropped, 'read', FILE_PATH).allowed).toBe(true)
    expect(checkBit({ ...file(0o077), uid: 0 }, dropped, 'r').allowed).toBe(false)
  })

  it('group 0 has no bypass and an inconsistent root flag cannot grant capabilities to a nonzero UID', () => {
    expect(checkBit(file(0), who({ uid: 1000680000, gid: 0 }), 'w').allowed).toBe(false)
    expect(checkBit(file(0), who({ uid: 1002, root: true }), 'r').allowed).toBe(false)
  })
})

describe('OpenShift, umask and setgid presets', () => {
  it.each([
    ['image', true], ['openshift', false], ['fixed', true], ['root', true], ['root-dropped', false], ['umask', false], ['setgid', true],
  ])('%s produces the intended default decision', (id, allowed) => {
    const p = preset(id as string)
    const before = JSON.stringify(p)
    const r = evaluateAccess(p.nodes, p.process, p.operation, p.target, p.umask)
    expect(r.allowed).toBe(allowed)
    expect(JSON.stringify(p)).toBe(before)
    expect(evaluateAccess(p.nodes, p.process, p.operation, p.target, p.umask)).toEqual(r)
  })

  it('changing runtime identity leaves image ownership unchanged; fixing the app tree copies owner bits to group 0', () => {
    const image = preset('image'), os = preset('openshift'), fixed = preset('fixed')
    expect(image.nodes).toEqual(os.nodes)
    expect(os.process).toMatchObject({ uid: 1000680000, gid: 0, root: false })
    for (const n of fixed.nodes.filter((n) => n.path.startsWith('/opt/app'))) expect(n).toMatchObject({ uid: 1001, gid: 0, mode: 0o775 })
    for (const n of fixed.nodes.filter((n) => !n.path.startsWith('/opt/app'))) expect(n).toEqual(image.nodes.find((x) => x.path === n.path))
    expect(last(evaluateAccess(fixed.nodes, fixed.process, 'write', FILE_PATH).trace)).toMatchObject({ class: 'group', bit: 'w', allowed: true })
    const supplementary = { ...fixed.process, gid: 1234, supplementaryGids: [0] }
    expect(evaluateAccess(fixed.nodes, supplementary, 'write', FILE_PATH).allowed).toBe(true)
  })

  it('umask removes bits at creation, does not grant bits, and never changes existing files', () => {
    const parent = { ...file(0o770), path: DATA_PATH, kind: 'dir' as const, gid: 0 }
    expect(createdFile(parent, who({ gid: 0 }), 0o077)).toMatchObject({ uid: 1001, gid: 0, mode: 0o600 })
    expect(createdFile(parent, who(), 0o022)).toMatchObject({ mode: 0o644 })
    expect(createdFile(parent, who(), 0o777)).toMatchObject({ mode: 0 })
    expect(createdFile(parent, who(), 0o000, 0o400).mode).toBe(0o400)
    expect(createdFile(parent, who(), 0o666, 0o600).mode).toBe(0) // bitwise masking, not subtraction
    const p = preset('fixed')
    expect(evaluateAccess(p.nodes, p.process, 'write', FILE_PATH, 0o077).allowed).toBe(true)
    const surprise = preset('umask')
    expect(last(evaluateAccess(surprise.nodes, surprise.process, 'read', FILE_PATH).trace)).toMatchObject({ class: 'group', bits: '---', allowed: false })
  })

  it('setgid chooses the new file group, not access rights or its permission bits', () => {
    const p = preset('setgid')
    const r = evaluateAccess(p.nodes, p.process, 'create', DATA_PATH, p.umask)
    expect(r.created).toEqual({ path: `${DATA_PATH}/new.txt`, kind: 'file', uid: 1002, gid: 2000, mode: 0o664 })
    const noSetgid = p.nodes.map((n) => ({ ...n, mode: n.mode & ~0o2000 }))
    expect(evaluateAccess(noSetgid, p.process, 'create', DATA_PATH, p.umask).created?.gid).toBe(1002)
    const noWrite = p.nodes.map((n) => n.path === DATA_PATH ? { ...n, mode: 0o2750 } : n)
    expect(evaluateAccess(noWrite, p.process, 'create', DATA_PATH).allowed).toBe(false)
    expect(evaluateAccess(p.nodes, { ...p.process, supplementaryGids: [] }, 'create', DATA_PATH).allowed).toBe(false)
    expect(createdFile({ ...file(0o777), path: '/', kind: 'dir' }, who(), 0).path).toBe('/new.txt')
  })

  it('presets return independent mutable values, so editing a scenario cannot corrupt a reset', () => {
    const a = permsPresets()
    a[0].nodes[0].mode = 0
    a.find((p) => p.id === 'setgid')!.process.supplementaryGids.push(99)
    expect(permsPresets()[0].nodes[0].mode).toBe(0o755)
    expect(preset('setgid').process.supplementaryGids).toEqual([2000])
  })
})

describe('validated inputs and ls/id rendering', () => {
  it('parses all nine permission bits and directory setgid with no unsupported special bits', () => {
    for (let n = 0; n <= 0o777; n++) {
      expect(parseMode(octalMode(n))).toBe(n)
      expect(parseMode('0' + octalMode(n))).toBe(n)
      expect(parseMode(octalMode(n | 0o2000), true)).toBe(n | 0o2000)
    }
    for (const bad of ['', '7', '77', '888', '0758', '755junk', ' 755', '-001', '0o755', '1000', '4755', '7777', '00000', '1.5']) expect(parseMode(bad, true)).toBeNull()
    expect(parseMode('2755')).toBeNull()
  })

  it('validates identity IDs without clamping, truncation or partial parsing', () => {
    expect(parseId('0')).toBe(0)
    expect(parseId('1000680000')).toBe(1000680000)
    expect(parseId('4294967294')).toBe(4294967294)
    for (const bad of ['', '-1', '1.2', '1e3', '0x10', '12x', ' 12', '4294967295', '99999999999999999999']) expect(parseId(bad)).toBeNull()
    expect(parseGids('')).toEqual([])
    expect(parseGids(' 0, 2000 2000 ')).toEqual([0, 2000])
    expect(parseGids('0, nope')).toBeNull()
    expect(parseGids('-1')).toBeNull()
  })

  it('renders rwx and directory s/S correctly, without fictitious metadata', () => {
    expect(rwx(0)).toBe('---')
    expect(rwx(7)).toBe('rwx')
    expect(symbolicMode(file(0o640))).toBe('-rw-r-----')
    const dir = { ...file(0o2770), kind: 'dir' as const, path: DATA_PATH }
    expect(symbolicMode(dir)).toBe('drwxrws---')
    expect(symbolicMode({ ...dir, mode: 0o2760 })).toBe('drwxrwS---')
    expect(lsLine(dir)).toBe(`drwxrws--- 1001 2000 ${DATA_PATH}`)
    expect(idLine(who({ supplementaryGids: [1001, 0, 0, 2000] }))).toBe('uid=1001 gid=1001 groups=1001,0,2000')
  })
})
