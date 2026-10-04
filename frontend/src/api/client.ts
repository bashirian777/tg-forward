import type { AuthInfo, TaskSnapshot, TaskConfig, RuntimeConfig, Deployment, SystemInfo, OperationLog, TaskError, CleanupResult } from '../types/api'

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number, public fields: Record<string, string> = {}) { super(message) }
}
export class StaleResponse extends Error {}
let csrf = ''
let generation = 0
let onUnauthorized = () => {}
export function setSession(info: AuthInfo) { csrf = info.csrf_token; generation++ }
export function clearSession() { csrf = ''; generation++ }
export function registerUnauthorized(callback: () => void) { onUnauthorized = callback }

interface Options { method?: string; data?: unknown; signal?: AbortSignal }
export async function request<T>(url: string, options: Options = {}): Promise<T> {
  const version = generation
  const headers: Record<string, string> = {}
  if (options.data !== undefined) headers['Content-Type'] = 'application/json'
  if (csrf) headers['X-CSRF-Token'] = csrf
  let response: Response
  try {
    response = await fetch(url, { method: options.method || 'GET', credentials: 'same-origin', headers,
      body: options.data === undefined ? undefined : JSON.stringify(options.data),
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000) })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError('network_error', '无法连接到服务，请稍后重试', 0)
  }
  if (version !== generation) throw new StaleResponse()
  const data = await response.json().catch(() => ({}))
  if (version !== generation) throw new StaleResponse()
  if (!response.ok) {
    if (response.status === 401 && url !== '/api/auth') { clearSession(); onUnauthorized() }
    throw new ApiError(data.error || 'request_failed', data.message || '请求失败', response.status, data.fields)
  }
  if (response.status === 202 && data.operation_id) {
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      if (version !== generation) throw new StaleResponse()
      const operation = await request<{ pending: boolean; result: T }>('/api/operations/' + data.operation_id, { signal: options.signal })
      if (!operation.pending) return operation.result
    }
  }
  return data as T
}
const taskPath = (id: string) => '/api/tasks/' + encodeURIComponent(id)
export const api = {
  session: () => request<AuthInfo>('/api/auth'),
  login: (password: string) => request<AuthInfo>('/api/auth', { method: 'POST', data: { password } }),
  logout: () => request('/api/auth', { method: 'DELETE' }),
  tasks: (signal?: AbortSignal) => request<TaskSnapshot[]>('/api/tasks', { signal }),
  task: (id: string) => request<TaskSnapshot>(taskPath(id)),
  create: (data: TaskConfig) => request('/api/tasks', { method: 'POST', data }),
  update: (id: string, data: TaskConfig & { revision: number; source_reset?: { last_message_id: number; clear_dedup: boolean } }) => request(taskPath(id), { method: 'PUT', data }),
  action: (id: string, action: string) => request(taskPath(id) + '/action', { method: 'POST', data: { action } }),
  remove: (id: string) => request(taskPath(id), { method: 'DELETE' }),
  checkpoint: (id: string, data: { last_message_id: number; forwarded_count: number }) => request(taskPath(id) + '/progress', { method: 'PUT', data }),
  errors: (id: string) => request<{ errors: TaskError[] }>(taskPath(id) + '/errors?limit=200'),
  clearErrors: (id: string) => request(taskPath(id) + '/errors', { method: 'DELETE' }),
  retry: (id: string) => request(taskPath(id) + '/transfer', { method: 'DELETE' }),
  skip: (id: string) => request(taskPath(id) + '/transfer/skip', { method: 'POST' }),
  clearDedup: (id: string) => request(taskPath(id) + '/dedup', { method: 'DELETE' }),
  cleanupTask: (id: string) => request<CleanupResult>(taskPath(id) + '/cleanup', { method: 'POST' }),
  config: (signal?: AbortSignal) => request<RuntimeConfig>('/api/config', { signal }),
  updateConfig: (data: Partial<RuntimeConfig> & { web_password?: string }) => request('/api/config', { method: 'PUT', data }),
  deployment: (signal?: AbortSignal) => request<Deployment>('/api/deployment', { signal }),
  system: (signal?: AbortSignal) => request<SystemInfo>('/api/system', { signal }),
  logs: (signal?: AbortSignal) => request<OperationLog[]>('/api/logs?limit=20', { signal }),
  cleanup: () => request<CleanupResult>('/api/cleanup', { method: 'POST' }),
}
