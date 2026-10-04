import { defineStore } from 'pinia'
import { ref } from 'vue'
export const useUI = defineStore('ui', () => {
  const toast = ref(''), newTask = ref(0)
  const confirmation = ref<{ title: string; message: string; danger: boolean } | null>(null)
  let resolver: ((value: boolean) => void) | null = null
  let timer: ReturnType<typeof setTimeout>
  function notify(message: string) { toast.value = message; clearTimeout(timer); timer = setTimeout(() => toast.value = '', 3500) }
  function confirm(title: string, message: string, danger = true): Promise<boolean> {
    resolve(false)
    confirmation.value = { title, message, danger }
    return new Promise(done => resolver = done)
  }
  function resolve(value: boolean) { const done = resolver; resolver = null; confirmation.value = null; done?.(value) }
  return { toast, newTask, confirmation, notify, confirm, resolve }
})
