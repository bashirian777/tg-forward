import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { TaskSnapshot, RuntimeConfig, Deployment, SystemInfo, OperationLog } from '../types/api'

export const useData = defineStore('data', () => {
  const tasks = ref<TaskSnapshot[]>([]), config = ref<RuntimeConfig | null>(null)
  const deployment = ref<Deployment | null>(null), system = ref<SystemInfo | null>(null), logs = ref<OperationLog[]>([])
  const pending = ref<Record<string, string>>({}), refreshVersion = ref(0), lastUpdated = ref('')
  function changed() { refreshVersion.value++ }
  async function load(key: 'tasks' | 'config' | 'deployment' | 'system' | 'logs', signal?: AbortSignal) {
    const value = await api[key](signal)
    if (signal?.aborted) return
    if (key === 'tasks') tasks.value = value as TaskSnapshot[]
    if (key === 'config') config.value = value as RuntimeConfig
    if (key === 'deployment') deployment.value = value as Deployment
    if (key === 'system') system.value = value as SystemInfo
    if (key === 'logs') logs.value = value as OperationLog[]
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  }
  async function run(id: string, action: string, operation: () => Promise<unknown>) {
    if (pending.value[id]) return
    const active = pending.value
    active[id] = action
    try { return await operation() } finally { delete active[id]; if (pending.value === active) changed() }
  }
  function reset() { tasks.value = []; config.value = null; deployment.value = null; system.value = null; logs.value = []; pending.value = {}; refreshVersion.value++ }
  return { tasks, config, deployment, system, logs, pending, refreshVersion, lastUpdated, changed, load, run, reset }
})
