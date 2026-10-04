<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { TaskSnapshot } from '../../types/api'
import { api } from '../../api/client'
import { useData } from '../../stores/data'
import { useUI } from '../../stores/ui'
import Modal from '../common/Modal.vue'
const props = defineProps<{ task: TaskSnapshot }>(), emit = defineEmits<{ close: [] }>()
const form = reactive({ last_message_id: props.task.progress.last_message_id, forwarded_count: props.task.progress.forwarded_count })
const busy = ref(false), error = ref(''), store = useData(), ui = useUI()
async function save() { busy.value = true; error.value = ''; try { await store.run(props.task.task_id, 'progress', () => api.checkpoint(props.task.task_id, form)); ui.notify('断点已保存'); emit('close') } catch (e) { error.value = (e as Error).message } finally { busy.value = false } }
</script>
<template><Modal id="checkpoint-modal" title="修改转发断点" :subtitle="task.config.note || task.task_id" small :busy="busy" @close="emit('close')"><form @submit.prevent="save"><div class="form-grid"><div class="form-field"><label for="checkpoint-last-id">最后处理的消息 ID</label><input id="checkpoint-last-id" v-model.number="form.last_message_id" type="number" min="0" step="1" required /></div><div class="form-field"><label for="checkpoint-count">累计转发条数</label><input id="checkpoint-count" v-model.number="form.forwarded_count" type="number" min="0" step="1" required /></div></div><p class="hint">手动调整可能造成重复或遗漏，请核对来源位置。</p><p class="modal-error" role="alert">{{ error }}</p><div class="modal-actions"><button type="button" class="btn ghost" :disabled="busy" @click="emit('close')">取消</button><button class="btn primary" :disabled="busy">保存断点</button></div></form></Modal></template>
