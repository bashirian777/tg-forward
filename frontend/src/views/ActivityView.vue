<script setup lang="ts">
import { useData } from '../stores/data'
import { usePolling } from '../composables/usePolling'
import { actionLabels, time } from '../format'
const store = useData(), poll = usePolling(['logs'], 15000)
</script>
<template><section class="view" data-page="activity" aria-label="操作记录"><div v-if="poll.error.value" class="banner" role="alert">{{ poll.error.value }}</div><div class="section-heading"><div><h2>操作记录</h2><p>最近的任务与配置变更。</p></div><span class="count">最近 {{ store.logs.length }} 条</span></div><div id="logs" class="card"><div v-if="!store.logs.length" class="empty">暂无操作记录</div><div v-for="log in store.logs" :key="log.id" class="log-row"><time class="log-when">{{ time(log.created_at) }}</time><div class="log-body"><div class="log-action" :class="log.result === 'success' ? 'ok' : 'err'">{{ actionLabels[log.action] || log.action }}</div><div class="log-detail">{{ log.task_id ? '任务 ' + log.task_id : '' }}</div></div><div class="log-task">{{ log.error }}</div></div></div></section></template>
