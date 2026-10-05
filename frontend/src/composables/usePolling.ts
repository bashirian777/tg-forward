import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useData } from '../stores/data'
import { StaleResponse } from '../api/client'

export function usePolling(keys: Parameters<ReturnType<typeof useData>['load']>[0][], interval: number) {
  const store = useData(), error = ref(''), loading = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined, controller: AbortController | undefined
  let stopped = false, queued = false, active: Promise<void> | undefined
  let unregisterRefresh: (() => void) | undefined
  function refresh(): Promise<void> {
    if (stopped || document.hidden) return Promise.resolve()
    if (active) { queued = true; return active }
    clearTimeout(timer); loading.value = true
    active = (async () => {
      do {
        queued = false
        const requestController = new AbortController()
        controller = requestController
        const results = await Promise.allSettled(keys.map(key => store.load(key, requestController.signal)))
        if (!stopped && !requestController.signal.aborted) {
          error.value = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected' && !(r.reason instanceof StaleResponse)).map(r => r.reason.message).join('；')
        }
      } while (queued && !stopped && !document.hidden)
    })().finally(() => {
      loading.value = false; active = undefined
      if (!stopped && !document.hidden && interval > 0) timer = setTimeout(refresh, interval)
    })
    return active
  }
  function visible() { if (document.hidden) { clearTimeout(timer); controller?.abort() } else void refresh() }
  onMounted(() => { unregisterRefresh = store.registerRefresh(refresh); void refresh(); document.addEventListener('visibilitychange', visible) })
  onUnmounted(() => { stopped = true; unregisterRefresh?.(); clearTimeout(timer); controller?.abort(); document.removeEventListener('visibilitychange', visible) })
  watch(() => store.refreshVersion, () => void refresh())
  return { error, loading, refresh }
}
