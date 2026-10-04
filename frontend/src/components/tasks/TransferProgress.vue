<script setup lang="ts">
import { computed } from 'vue'
import type { Transfer } from '../../types/api'
import { bytes, transferLabels } from '../../format'
import Icon from '../common/Icon.vue'
const props = defineProps<{ transfer: Transfer }>()
const percent = computed(() => Math.max(0, Math.min(100, Number(props.transfer.percent) || 0)))
</script>
<template><div class="transfer-strip" :class="{ 'has-error': transfer.state === 'error' }">
  <div class="transfer-heading"><span class="transfer-type"><Icon :name="transfer.type === 'upload' ? 'up' : 'down'" />{{ transferLabels[transfer.state] || '等待处理' }}</span><span class="transfer-percent">{{ percent.toFixed(1) }}%</span></div>
  <div class="transfer-filename" :title="transfer.filename">{{ transfer.filename || '正在准备媒体' }}</div>
  <div class="progress" role="progressbar" aria-label="文件传输进度" :aria-valuenow="percent" :aria-valuemin="0" :aria-valuemax="100"><div class="fill" :class="{ up: transfer.type === 'upload' }" :style="{ width: percent + '%' }"></div></div>
  <div class="transfer-meta"><span>文件 {{ transfer.file_index || 1 }} / {{ transfer.total_files || 1 }}</span><span>{{ bytes(transfer.current) }} / {{ bytes(transfer.total) }}</span><span>{{ transfer.speed_bps ? bytes(transfer.speed_bps) + '/s' : '计算速度中' }}</span></div>
</div></template>
