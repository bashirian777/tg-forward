<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import Icon from './Icon.vue'
const props = defineProps<{ id: string; title: string; subtitle?: string; small?: boolean; busy?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
function close() { if (!props.busy) emit('close') }
function keyboard(event: KeyboardEvent) {
  if (event.key !== 'Tab') return
  const items = [...(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), summary, [tabindex="0"]') || [])].filter(el => el.getClientRects().length > 0)
  const first = items[0], last = items.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(() => { dialog.value?.showModal(); document.body.classList.add('modal-open') })
onBeforeUnmount(() => { dialog.value?.close(); if (document.querySelectorAll('dialog[open]').length === 0) document.body.classList.remove('modal-open') })
</script>
<template>
  <Teleport to="body">
    <dialog :id="id" ref="dialog" class="modal" :aria-labelledby="id + '-title'" tabindex="-1" @keydown="keyboard" @cancel.prevent="close" @click="($event.target === dialog) && close()">
      <div class="modal-panel" :class="{ sm: small }">
        <div class="modal-head"><div><h2 :id="id + '-title'">{{ title }}</h2><p v-if="subtitle" class="subtitle">{{ subtitle }}</p></div>
          <button class="modal-close" type="button" aria-label="关闭" :disabled="busy" @click="close"><Icon name="x" /></button>
        </div>
        <slot />
      </div>
    </dialog>
  </Teleport>
</template>
