export type CommandResult = { source: 'recording' | 'live' | 'simulation'; expected: 'ok' | 'fail' | 'any'; status: 'ok' | 'fail' | 'error'; matched: boolean }

/** A refused/missing/timed-out execution is not an expected command failure, even when expected=any. */
export function commandResult(source: CommandResult['source'], expected: CommandResult['expected'], code?: number | null, executionStatus?: string): CommandResult {
  const error = code == null || code < 0 || code === 124 || !!executionStatus && !['ok', 'error'].includes(executionStatus)
  const status = error ? 'error' : code === 0 ? 'ok' : 'fail'
  return { source, expected, status, matched: !error && (expected === 'any' || expected === status) }
}
