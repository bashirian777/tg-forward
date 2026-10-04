<script setup lang="ts">
import { computed, ref } from 'vue'
import { useData } from '../stores/data'
import { useUI } from '../stores/ui'
import { usePolling } from '../composables/usePolling'
import { api } from '../api/client'
import { bytes, load, uptime } from '../format'
import Icon from '../components/common/Icon.vue'
const store = useData(), ui = useUI(), poll = usePolling(['system'], 15000)
usePolling(['config'], 0)
const busy = ref(false), disk = computed(() => store.system?.temp_disk)
const low = computed(() => disk.value && disk.value.free < (store.config?.min_free_disk_mb || 0) * 1024 ** 2)
async function cleanup() { if (!await ui.confirm('清理临时文件', '删除非活动传输的媒体与续传资料；活动传输保留，失败任务可能需要重新下载。')) return; busy.value = true; try { const result = await api.cleanup(); store.changed(); ui.notify(`已删除 ${result.removed} 个文件，释放 ${bytes(result.freed_bytes)}${result.errors?.length ? '，部分删除失败' : ''}`) } catch (e) { ui.notify((e as Error).message) } finally { busy.value = false } }
</script>
<template><section class="view" data-page="resources" aria-label="系统资源"><div v-if="poll.error.value" class="banner" role="alert">{{ poll.error.value }}</div><div class="section-heading"><div><h2>资源概况</h2><p>关注临时目录可用空间，确保媒体传输顺利完成。</p></div><button id="cleanup-temp-btn" class="btn" :disabled="busy" @click="cleanup"><Icon name="trash" />清理临时文件</button></div><div v-if="low" class="banner" role="alert">临时目录所在磁盘空间偏低，传输可能等待释放空间。</div><div class="system-grid"><article class="card resource-card"><span class="resource-icon"><Icon name="disk" /></span><div class="config-item"><span class="k">临时目录所在磁盘</span><span class="v">{{ disk ? bytes(disk.free) + ' 可用' : '目录尚未创建' }}</span><span class="sub">{{ disk ? bytes(disk.used) + ' / ' + bytes(disk.total) + ' · ' + disk.percent + '% 已用' : '—' }}</span></div><div class="progress"><div class="fill" :style="{ width: (disk?.percent || 0) + '%' }"></div></div></article><article class="card resource-card"><span class="resource-icon"><Icon name="folder" /></span><div class="config-item"><span class="k">临时文件</span><span class="v">{{ store.system?.temp_exists ? '可用' : '不存在' }}</span><span class="sub">{{ store.system?.temp_dir }} · {{ store.system?.temp_files.files || 0 }} 个临时文件，{{ bytes(store.system?.temp_files.bytes) }}</span></div></article><article class="card resource-card"><span class="resource-icon"><Icon name="activity" /></span><div class="config-item"><span class="k">系统负载</span><span class="v">{{ load(store.system?.load_average) }}</span><span class="sub">运行 {{ uptime(store.system?.uptime_seconds) }}</span></div></article></div><div class="info-note"><Icon name="folder" /><div><h3>临时文件会自动清理</h3><p>正在使用的文件会保留，失败任务可能需要重新下载。保留周期设为 0 时关闭自动过期清理。</p></div></div></section></template>
