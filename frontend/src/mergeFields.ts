// These forms contain scalar values and string arrays; compare arrays by content.
export interface FieldConflict {
  key: string
  baseline: unknown
  current: unknown
  latest: unknown
  choice?: 'current' | 'latest'
}
export function mergeFields<T extends object>(baseline: T, current: T, latest: T) {
  const merged = { ...current }, conflicts: FieldConflict[] = []
  const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
  for (const key of Object.keys(baseline) as (keyof T & string)[]) {
    if (equal(current[key], baseline[key])) merged[key] = latest[key]
    else if (!equal(latest[key], baseline[key]) && !equal(current[key], latest[key])) {
      conflicts.push({ key, baseline: baseline[key], current: current[key], latest: latest[key] })
    }
  }
  return { merged, conflicts }
}
