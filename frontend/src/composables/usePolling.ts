import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useData } from '../stores/data'
import { StaleResponse } from '../api/client'

export function usePolling(keys: Parameters<ReturnType<typeof useData>['load']>[0][], interval: number) {
  const store = useData(), error = ref(''), loading = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined, controller: AbortController | undefined
  let stopped = false, queued = false
  async function refresh() {
    if (stopped || document.hidden) return
    if (loading.value) { queued = true; return }
    clearTimeout(timer); loading.value = true; controller = new AbortController()
    try {
      const results = await Promise.allSettled(keys.map(key => store.load(key, controller?.signal)))
      if (stopped || controller.signal.aborted) return
      error.value = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected' && !(r.reason instanceof StaleResponse)).map(r => r.reason.message).join('；')
    } finally {
      loading.value = false
      if (!stopped && !document.hidden && (queued || interval > 0)) { timer = setTimeout(refresh, queued ? 0 : interval); queued = false }
    }
  }
  function visible() { if (document.hidden) { clearTimeout(timer); controller?.abort() } else void refresh() }
  onMounted(() => { void refresh(); document.addEventListener('visibilitychange', visible) })
  onUnmounted(() => { stopped = true; clearTimeout(timer); controller?.abort(); document.removeEventListener('visibilitychange', visible) })
  watch(() => store.refreshVersion, () => void refresh())
  return { error, loading, refresh }
}
