import { useId, useState } from 'react'
import {
  DATA_PATH, FILE_PATH, OPERATIONS, evaluateAccess, idLine, lsLine, octalMode, parseGids, parseId,
  parseMode, permsPresets, type FsNode, type Operation, type PermsPreset, type ProcessIdentity,
} from './perms'
import { Chip, Code, Panel, SelectField, SimIcon, SimShell, Toggle, useAnnouncer, type ModelScope } from './ui'

const PRESETS = permsPresets()
const SCOPE: ModelScope = {
  includes: [
    'One absolute path: ancestor search (x), then exactly one owner, group or other class at each node; primary and supplementary group membership.',
    'File read/write/execute, directory listing (names only) and entry, and parent w+x for creation or deletion. A trace stops at the first denial.',
    'UID 0 with both DAC capabilities retained or both dropped. CAP_DAC_OVERRIDE still needs at least one x bit to execute a regular file; directory search has no such restriction.',
    'Creation previews: requested mode & ~umask, and group inheritance from a setgid parent. A regular new file does not inherit the setgid bit.',
    'OpenShift 4.21 arbitrary UID and root-group membership; the documented chgrp -R 0 && chmod -R g=u recipe on the app tree.',
  ],
  leavesOut: [
    'ACLs (including default ACLs), SELinux and other mandatory access controls. Allowed here means the modelled DAC checks pass.',
    'Capabilities beyond CAP_DAC_OVERRIDE and CAP_DAC_READ_SEARCH. These two are coupled to UID 0 here; Linux can grant them separately, including to nonzero UIDs. Container policies can drop them.',
    'The sticky bit: real sticky directories restrict deletion to the file owner, directory owner or a suitably privileged process.',
    'NFS root squash, user namespace UID/GID mappings, separate fsuid/fsgid, symlinks and hard links.',
    'Read-only and noexec mounts, immutable/append-only flags, file contents, executable formats and interpreter permissions. Execute here checks DAC only.',
    'SCC admission and volume ownership changes (fsGroup). The example UID is illustrative, not a guaranteed assignment. Creation/deletion are previews; the tree is not mutated.',
  ],
  links: [
    { label: 'Linux: path_resolution(7)', url: 'https://man7.org/linux/man-pages/man7/path_resolution.7.html' },
    { label: 'Linux: capabilities(7)', url: 'https://man7.org/linux/man-pages/man7/capabilities.7.html' },
    { label: 'Linux: inode(7) — rwx, setgid and sticky bit', url: 'https://man7.org/linux/man-pages/man7/inode.7.html' },
    { label: 'Linux: umask(2)', url: 'https://man7.org/linux/man-pages/man2/umask.2.html' },
    { label: 'OpenShift 4.21: Creating images — Support arbitrary user ids', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/images/creating-images' },
  ],
}

type NodeDraft = { path: string; kind: FsNode['kind']; uid: string; gid: string; mode: string }
type Draft = { uid: string; gid: string; groups: string; dropped: boolean; nodes: NodeDraft[]; umask: string; requested: string }
function draftFor(p: PermsPreset): Draft {
  return {
    uid: String(p.process.uid), gid: String(p.process.gid), groups: p.process.supplementaryGids.join(', '), dropped: p.process.capabilitiesDropped,
    nodes: p.nodes.map((n) => ({ ...n, uid: String(n.uid), gid: String(n.gid), mode: octalMode(n.mode) })),
    umask: octalMode(p.umask), requested: '666',
  }
}
const ID_ERROR = 'Use a whole decimal ID from 0 to 4294967294.'
const MODE_ERROR = 'Use three octal digits (000–777), optionally prefixed by 0.'

function ValidatedField({ label, value, onChange, error, hint }: { label: string; value: string; onChange: (value: string) => void; error?: string; hint?: string }) {
  const helpId = useId()
  const labelId = useId() // the accessible name is the label alone; the error or hint is its description
  return (
    <label className="sim-field">
      <span className="sim-label" id={labelId}>{label}</span>
      <input type="text" inputMode="numeric" className="sim-mono" spellCheck={false} value={value} aria-labelledby={labelId} aria-invalid={!!error} aria-describedby={hint || error ? helpId : undefined} onChange={(e) => onChange(e.target.value)} />
      {(error || hint) && <span id={helpId} className={error ? 'sim-field-error' : 'sim-hint-text'}>{error || hint}</span>}
    </label>
  )
}

function NodeEditor({ node, onChange }: { node: NodeDraft; onChange: (patch: Partial<NodeDraft>) => void }) {
  const directory = node.kind === 'dir'
  const mode = parseMode(node.mode, directory)
  const valid = mode !== null && parseId(node.uid) !== null && parseId(node.gid) !== null
  const setBit = (mask: number, checked: boolean) => {
    if (mode !== null) onChange({ mode: octalMode(checked ? mode | mask : mode & ~mask) })
  }
  return (
    <fieldset className="sim-perms-node">
      <legend><code>{node.path}</code> · {directory ? 'directory' : 'file'}</legend>
      {valid && <Code label={`Permissions of ${node.path}`}>{lsLine({ ...node, mode: mode!, uid: Number(node.uid), gid: Number(node.gid) })}</Code>}
      <div className="sim-row">
        <ValidatedField label={`Owner UID: ${node.path}`} value={node.uid} onChange={(uid) => onChange({ uid })} error={parseId(node.uid) === null ? ID_ERROR : undefined} />
        <ValidatedField label={`Group GID: ${node.path}`} value={node.gid} onChange={(gid) => onChange({ gid })} error={parseId(node.gid) === null ? ID_ERROR : undefined} />
        <ValidatedField label={`Octal mode: ${node.path}`} value={node.mode} onChange={(m) => onChange({ mode: m })} error={mode === null ? directory ? 'Use 000–777, or 2000–2777 for setgid directories (e.g. 2770).' : MODE_ERROR : undefined} />
      </div>
      <div className="sim-perms-bits">
        {(['owner', 'group', 'other'] as const).map((c, i) => (
          <fieldset key={c}>
            <legend>{c}</legend>
            {(['r', 'w', 'x'] as const).map((bit, j) => {
              const mask = (4 >> j) << (6 - i * 3)
              return <label key={bit}><input type="checkbox" aria-label={`${c} ${bit}: ${node.path}`} disabled={mode === null} checked={mode !== null && !!(mode & mask)} onChange={(e) => setBit(mask, e.target.checked)} />{bit}</label>
            })}
          </fieldset>
        ))}
      </div>
      {directory && <Toggle label={`Setgid: ${node.path}`} checked={mode !== null && !!(mode & 0o2000)} disabled={mode === null} onChange={(v) => setBit(0o2000, v)} hint="New children inherit this directory’s GID; this does not grant write permission." />}
    </fieldset>
  )
}

export default function PermsSim() {
  const [presetId, setPresetId] = useState('openshift')
  const initial = PRESETS.find((p) => p.id === 'openshift')!
  const [draft, setDraft] = useState(() => draftFor(initial))
  const [operation, setOperation] = useState<Operation>(initial.operation)
  const [directory, setDirectory] = useState(DATA_PATH)
  const [prediction, setPrediction] = useState<'allowed' | 'denied' | null>(null)
  const [msg, announce] = useAnnouncer()
  const predictionId = useId()
  const preset = PRESETS.find((p) => p.id === presetId)
  const uid = parseId(draft.uid), gid = parseId(draft.gid), groups = parseGids(draft.groups)
  const nodes = draft.nodes.map((n) => ({ ...n, uid: parseId(n.uid), gid: parseId(n.gid), mode: parseMode(n.mode, n.kind === 'dir') }))
  const umask = parseMode(draft.umask), requested = parseMode(draft.requested)
  const valid = uid !== null && gid !== null && groups !== null && nodes.every((n) => n.uid !== null && n.gid !== null && n.mode !== null) && (operation !== 'create' || (umask !== null && requested !== null))
  const identity: ProcessIdentity | null = uid !== null && gid !== null && groups !== null ? { uid, gid, supplementaryGids: groups, root: uid === 0, capabilitiesDropped: draft.dropped } : null
  const directoryOp = operation === 'list' || operation === 'enter' || operation === 'create'
  const target = directoryOp ? directory : FILE_PATH
  const result = prediction && valid && identity ? evaluateAccess(nodes as FsNode[], identity, operation, target, umask ?? 0o022, requested ?? 0o666) : null

  const resetPrediction = () => {
    if (prediction) announce('Scenario changed. Make a new prediction to see the result.')
    setPrediction(null)
  }
  const edit = (patch: Partial<Draft>) => { setDraft((d) => ({ ...d, ...patch })); setPresetId('custom'); resetPrediction() }
  const pickPreset = (id: string) => {
    const p = PRESETS.find((x) => x.id === id)
    if (!p) return
    setPresetId(id); setDraft(draftFor(p)); setOperation(p.operation); setDirectory(p.target === FILE_PATH ? DATA_PATH : p.target); resetPrediction()
    announce(`Preset loaded: ${p.label}. Make a prediction.`)
  }
  return (
    <SimShell id="perms" title="Who may touch this file? Linux permissions and OpenShift’s arbitrary UID"
      scenario={<><p>An image’s app tree belongs to UID 1001. OpenShift runs the same image with an arbitrary UID and membership in group 0. Which operations still work?</p><p>Choose a preset or edit the process and tree, choose an operation, then predict allowed or denied. Predictions are not scored or saved.</p></>}
      scope={SCOPE} challenges={[]} announcement={msg}>
      <div className="sim-work sim-perms-work">
        <div className="sim-col">
          <Panel title="Scenario and process">
            <div className="sim-form">
              <SelectField label="Preset" value={presetId} options={[...PRESETS.map((p) => ({ value: p.id, label: p.label })), ...(presetId === 'custom' ? [{ value: 'custom', label: 'Custom (edited scenario)' }] : [])]} onChange={pickPreset} />
              <p className="sim-note">{preset?.note || 'Custom scenario. Each node selects exactly one class: matching owner first, otherwise a matching group, otherwise other. No fallback to more permissive bits.'}</p>
              <div className="sim-row">
                <ValidatedField label="Process UID" value={draft.uid} onChange={(v) => edit({ uid: v })} error={uid === null ? ID_ERROR : undefined} />
                <ValidatedField label="Primary GID" value={draft.gid} onChange={(v) => edit({ gid: v })} error={gid === null ? ID_ERROR : undefined} />
              </div>
              <ValidatedField label="Supplementary GIDs" value={draft.groups} onChange={(v) => edit({ groups: v })} error={groups === null ? 'Use decimal IDs separated by spaces or commas.' : undefined} hint="A comma or space separated list; leave empty for none." />
              <Toggle label="Root (UID 0)" checked={uid === 0} onChange={(v) => edit({ uid: v ? '0' : '1001' })} hint="Updates the UID. Group 0 membership alone does not make a process root." />
              <Toggle label="Capabilities dropped (both DAC capabilities)" checked={draft.dropped} onChange={(v) => edit({ dropped: v })} hint="Disables the model’s root bypass. Without this toggle, UID 0 has CAP_DAC_OVERRIDE and CAP_DAC_READ_SEARCH here." />
              {identity && <Code label="Process id output">{`$ id\n${idLine(identity)}`}</Code>}
            </div>
          </Panel>
          <Panel title="Operation">
            <div className="sim-form">
              <SelectField label="Operation" value={operation} options={OPERATIONS} onChange={(v) => { setOperation(v); resetPrediction() }} />
              {directoryOp && <SelectField label="Target directory" value={directory} options={draft.nodes.filter((n) => n.kind === 'dir').map((n) => ({ value: n.path, label: n.path }))} onChange={(v) => { setDirectory(v); resetPrediction() }} />}
              <p className="sim-note">Target: <code>{target}</code>{operation === 'create' ? ' → new.txt (a new file)' : operation === 'delete' ? ' (unlink the existing entry)' : ''}</p>
              {operation === 'list' && <p className="sim-note">Lists names only (like ls without -l). Looking up entries or their metadata also needs directory x.</p>}
              {(operation === 'create' || operation === 'delete') && <p className="sim-note">Parent directory w+x controls this operation. The existing file’s write bit controls changing its contents. Sticky-bit restrictions are left out.</p>}
              {operation === 'create' && <div className="sim-row">
                <ValidatedField label="Umask for creation" value={draft.umask} onChange={(v) => edit({ umask: v })} error={umask === null ? MODE_ERROR : undefined} />
                <ValidatedField label="Requested file mode" value={draft.requested} onChange={(v) => edit({ requested: v })} error={requested === null ? MODE_ERROR : undefined} />
              </div>}
              <section className="sim-predict" aria-labelledby={predictionId}>
                <h3 className="sim-kicker" id={predictionId}><SimIcon name="bulb" /> Predict first</h3>
                <p>Will this operation be allowed? Your prediction is not scored.</p>
                <div className="sim-actions" role="group" aria-label="Your prediction">
                  {(['allowed', 'denied'] as const).map((choice) => <button type="button" className="sim-btn" key={choice} disabled={!valid} aria-pressed={prediction === choice} onClick={() => {
                    setPrediction(choice)
                    const decision = evaluateAccess(nodes as FsNode[], identity!, operation, target, umask ?? 0o022, requested ?? 0o666)
                    announce(`You predicted ${choice}. Result: ${decision.allowed ? 'allowed' : 'denied'}. ${decision.reason}`)
                  }}>Predict {choice}</button>)}
                </div>
                {!valid && <p className="sim-field-error">Fix the highlighted inputs before predicting.</p>}
              </section>
            </div>
          </Panel>
        </div>
        <div className="sim-col">
          <Panel title="Result and path walk">
            {result ? <div className="sim-form" data-testid="perms-result">
              <div className="sim-banner" data-tone={result.allowed ? 'ok' : 'bad'}>
                <SimIcon name={result.allowed ? 'check' : 'x'} />
                <div className="sim-banner-body">
                  <p><strong>{result.allowed ? 'Allowed' : `Denied (${result.error})`}</strong> · You predicted {prediction}.</p>
                  <p>{result.reason}</p>
                </div>
              </div>
              <ol className="sim-path" aria-label="Permission trace">
                {result.trace.map((step, i) => <li className="sim-hop" key={i} data-state={step.allowed ? 'ok' : 'fail'}>
                  <span className="sim-hop-dot" aria-hidden="true"><SimIcon name={step.allowed ? 'check' : 'x'} size={14} /></span>
                  <div className="sim-hop-body">
                    <p className="sim-hop-label"><code>{step.path}</code> <Chip tone={step.allowed ? 'ok' : 'bad'}>{step.allowed ? 'allowed' : 'denied'}</Chip></p>
                    <p className="sim-hop-detail">{step.phase === 'search' ? 'Ancestor search' : 'Operation'} · {step.class} · needs <code>{step.bit}</code></p>
                    <p className="sim-hop-detail">{step.reason}</p>
                  </div>
                </li>)}
              </ol>
              {result.created && <div className="sim-form">
                <p className="sim-note">Creation preview (the tree below stays unchanged):</p>
                <Code label="New file permissions">{lsLine(result.created)}</Code>
                <p className="sim-note">Mode: <code>{octalMode(requested!)} &amp; ~{octalMode(umask!)} = {octalMode(result.created.mode)}</code>. Owner UID {result.created.uid}; GID {result.created.gid} comes from {nodes.find((n) => n.path === target)!.mode! & 0o2000 ? 'the setgid parent' : 'the process’s primary group'}.</p>
              </div>}
            </div> : <p className="sim-note">Make a prediction to reveal the decision and each permission check. Editing any input hides the previous result.</p>}
          </Panel>
          <Panel title="Filesystem: edit owners and modes">
            <div className="sim-form">
              <p className="sim-note">Each line shows type + rwx, numeric UID, GID and path (ls -l style). Directory x means search. Octal inputs and checkboxes edit the same bits. Values are scenario edits, not commands run by the process.</p>
              {draft.nodes.map((n, i) => <NodeEditor key={n.path} node={n} onChange={(patch) => edit({ nodes: draft.nodes.map((x, j) => i === j ? { ...x, ...patch } : x) })} />)}
            </div>
          </Panel>
        </div>
      </div>
    </SimShell>
  )
}
