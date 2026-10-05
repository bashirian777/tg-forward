export interface TaskConfig {
  task_id: string; source_channel: number; target_channel: number;
  min_delay: number; max_delay: number; enabled: boolean; note: string;
  hide_source: boolean; caption_prefix: string; filter_keywords: string[];
  required_hashtags: string[]; target_topic_id: number | null; source_topic_id: number | null;
  remove_hashtags: boolean; send_as_channel: boolean; deduplicate: boolean; require_video: boolean; include_topic_name: boolean;
}
export interface Progress { last_message_id: number; forwarded_count: number; last_forward_time: string }
export interface Transfer {
  type: string; state: string; filename: string; percent: number;
  current: number; total: number; speed_bps: number; file_index: number; total_files: number;
}
export interface TaskSnapshot {
  task_id: string; status: 'running' | 'stopped' | 'error'; revision: number;
  config: TaskConfig; progress: Progress; transfer: Transfer | null;
  errors: { unresolved: number; count: number };
}
export type TaskSortMode = 'manual' | 'recent'
export interface TaskList { tasks: TaskSnapshot[]; sort_mode: TaskSortMode }
export interface RuntimeConfig {
  revision: number; temp_dir: string; temp_max_age_hours: number; web_auth_ttl_hours: number;
  web_password_configured: boolean; max_concurrent_tasks: number; min_free_disk_mb: number;
  download_workers: number; upload_workers: number;
}
export type RuntimeConfigUpdate = Omit<RuntimeConfig, 'web_password_configured'> & { web_password?: string }
export interface Deployment {
  services: Record<string, { state: string; message: string }>;
  fields: Record<string, { configured?: boolean; value?: string | number | number[]; source: string }>;
}
export interface Disk { total: number; free: number; used: number; percent: number }
export interface SystemInfo {
  disk: Disk; temp_disk: Disk | null; temp_dir: string; temp_exists: boolean;
  temp_files: { files: number; bytes: number }; uptime_seconds: number; load_average: number[];
}
export interface OperationLog { id: number; action: string; task_id?: string; result: string; error?: string; created_at: string }
export interface TaskError { id: number; stage: string; filename?: string; message_id?: number; error: string; details?: string; resolved: boolean; created_at: string }
export interface AuthInfo { auth_required: boolean; authenticated: boolean; csrf_token: string; expires_at: number }
export interface CleanupResult { removed: number; freed_bytes: number; errors: unknown[] }
