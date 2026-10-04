import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, clearSession, registerUnauthorized, setSession } from '../api/client'
import type { AuthInfo } from '../types/api'

export const useAuth = defineStore('auth', () => {
  const ready = ref(false), loading = ref(true), error = ref(''), info = ref<AuthInfo | null>(null)
  registerUnauthorized(() => { ready.value = false; info.value = null; error.value = '登录已过期，请重新输入密码' })
  function accept(value: AuthInfo) { info.value = value; ready.value = value.authenticated; setSession(value); error.value = '' }
  async function init() {
    // Remove bearer tokens from installations predating Cookie sessions.
    localStorage.removeItem('tg_forwarder_web_token'); localStorage.removeItem('tg_forwarder_web_expiry')
    try { const current = await api.session(); accept(current.authenticated ? current : !current.auth_required ? await api.login('') : current) }
    catch (e) { error.value = (e as Error).message }
    finally { loading.value = false }
  }
  async function login(password: string) { accept(await api.login(password)) }
  async function logout() {
    try { await api.logout() } finally { clearSession(); ready.value = false; info.value = null; error.value = '' }
  }
  return { ready, loading, error, info, init, login, logout }
})
