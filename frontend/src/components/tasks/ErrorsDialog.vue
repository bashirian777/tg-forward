<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { TaskSnapshot, TaskError } from '../../types/api'
import { api } from '../../api/client'
import { useData } from '../../stores/data'
import { useUI } from '../../stores/ui'
import { time } from '../../format'
import Modal from '../common/Modal.vue'
const props = defineProps<{ task: TaskSnapshot }>(), emit = defineEmits<{ close: [] }>()
const records = ref<TaskError[]>([]), loading = ref(true), busy = ref(false), error = ref(''), ui = useUI(), store = useData()
onMounted(async () => { try { records.value = (await api.errors(props.task.task_id)).errors } catch (e) { error.value = (e as Error).message } finally { loading.value = false } })
async function clear() { if (!await ui.confirm('清空错误记录', '删除该任务的错误历史，保留转发断点。')) return; busy.value = true; try { await api.clearErrors(props.task.task_id); records.value = []; store.changed(); ui.notify('错误记录已清空') } catch (e) { error.value = (e as Error).message } finally { busy.value = false } }
</script>
<template><Modal id="errors-modal" title="任务错误记录" :subtitle="task.task_id" :busy="busy" @close="emit('close')"><div v-if="loading" class="empty">正在读取错误记录…</div><div v-else-if="!records.length" class="empty">暂无错误记录</div><div v-else id="error-list"><article v-for="item in records" :key="item.id" class="error-item" :class="{ resolved: item.resolved }"><div class="error-item-head"><span>{{ item.stage }}</span><time>{{ time(item.created_at) }}</time></div><div class="error-item-meta">{{ item.filename }} {{ item.message_id ? '消息 ' + item.message_id : '' }} {{ item.resolved ? '已解决' : '' }}</div><pre class="error-item-message">{{ item.error }}{{ item.details ? '\n\n' + item.details : '' }}</pre></article></div><p class="modal-error" role="alert">{{ error }}</p><div class="modal-actions"><button id="clear-errors-btn" class="btn danger" :disabled="busy || loading" @click="clear">清空记录</button><button class="btn" :disabled="busy" @click="emit('close')">关闭</button></div></Modal></template>
