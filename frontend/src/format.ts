export function bytes(value = 0) {
  if (value < 1024) return value + ' B'
  if (value < 1024 ** 2) return (value / 1024).toFixed(1) + ' KB'
  if (value < 1024 ** 3) return (value / 1024 ** 2).toFixed(1) + ' MB'
  return (value / 1024 ** 3).toFixed(2) + ' GB'
}
export function time(iso?: string) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const diff = (Date.now() - date.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前'
  if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' 天前'
  return date.toLocaleString('zh-CN', { hour12: false })
}
export function uptime(seconds = 0) {
  return (seconds >= 86400 ? Math.floor(seconds / 86400) + ' 天 ' : '') + Math.floor(seconds % 86400 / 3600) + ' 小时 ' + Math.floor(seconds % 3600 / 60) + ' 分钟'
}
export function load(values?: number[]) {
  return values?.length ? values.map(value => value.toFixed(2)).join(' / ') : '—'
}
export const statusLabels: Record<string, string> = { running: '运行中', stopped: '已停止', error: '发生错误' }
export const transferLabels: Record<string, string> = { error: '传输失败', interrupted: '已中断', fetching: '准备媒体', waiting_disk: '等待磁盘空间', sending: '等待发送确认', downloading: '下载中', uploading: '上传中' }
// Keep labels for actions recorded by older versions.
export const actionLabels: Record<string, string> = { task_sort: '修改任务排序方式', task_move: '调整任务顺序', start_task: '启动任务', pause_task: '暂停任务', resume_task: '恢复任务', stop_task: '停止任务', create_task: '创建任务', update_task: '更新任务', delete_task: '删除任务', update_app_config: '修改运行设置', set_progress: '修改断点', clear_dedup: '清空去重记录', clear_transfer: '重试传输', skip_transfer: '跳过媒体组', transfer_error: '传输错误', transfer_metrics: '传输完成', cleanup_files: '清理任务文件', clear_task_errors: '清空错误记录' }
