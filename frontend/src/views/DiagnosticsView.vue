<script setup>
import { computed, inject, onUnmounted, ref, watch } from 'vue';
import { Download, FileText, Play, RefreshCw, Stethoscope } from '@lucide/vue';
import { api } from '../api.js';
import { formatTime } from '../format.js';
import ModalDialog from '../components/ModalDialog.vue';

const notify = inject('notify');
const report = ref(null);
const rooms = ref([]);
const room = ref('');
const issues = ref([]);
const issueScope = ref('');
const busy = ref(false);
const issuesBusy = ref(false);
const error = ref('');
const issuesError = ref('');
const testWrite = ref(false);
const platformResult = ref(null);
const encoderResult = ref(null);
const encoder = ref('');
const exportOpen = ref(false);
const exporting = ref(false);
const exportError = ref('');
const start = ref('');
const end = ref('');
let disposed = false;
let issueGeneration = 0;
const hardware = computed(() => (report.value?.encoders?.encoders || []).filter((item) => /_(nvenc|qsv|amf|videotoolbox)$/.test(item.value)));
const statusLabel = (value) => ({ ok: '正常', warning: '警告', failed: '失败', unchecked: '未检查' }[value] || value);

async function loadIssues() {
  const id = ++issueGeneration;
  issuesBusy.value = true;
  try {
    const data = await api.runtimeIssues({ room_id: room.value || undefined });
    if (!disposed && id === issueGeneration) { issues.value = data.issues || []; issueScope.value = data.scope; issuesError.value = ''; }
  } catch (err) { if (!disposed && id === issueGeneration) issuesError.value = err.message; }
  finally { if (!disposed && id === issueGeneration) issuesBusy.value = false; }
}
async function action(kind) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    if (kind === 'environment') {
      const data = await api.diagnose({ test_write: testWrite.value });
      if (!disposed) { report.value = data; encoder.value = hardware.value.find((item) => item.available)?.value || ''; encoderResult.value = null; }
    } else if (kind === 'platform') {
      const data = await api.diagnosePlatform(room.value);
      if (!disposed) platformResult.value = data;
    } else {
      const data = await api.diagnoseEncoder(encoder.value);
      if (!disposed) encoderResult.value = data;
    }
  } catch (err) { if (!disposed) error.value = err.message; }
  finally { if (!disposed) { busy.value = false; loadIssues(); } }
}
async function download() {
  if (exporting.value) return;
  exporting.value = true;
  exportError.value = '';
  try {
    const blob = await api.exportDiagnostics({ room_id: room.value ? Number(room.value) : undefined,
      start: start.value ? new Date(start.value).toISOString() : undefined, end: end.value ? new Date(end.value).toISOString() : undefined });
    if (disposed) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'LiveRecorder-diagnostics.zip';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    exportOpen.value = false;
    notify('诊断包已导出');
  } catch (err) { if (!disposed) exportError.value = err.message; }
  finally { if (!disposed) exporting.value = false; }
}
watch(room, () => { platformResult.value = null; loadIssues(); });
onUnmounted(() => { disposed = true; issueGeneration += 1; });
api.rooms().then((data) => { if (!disposed) rooms.value = data; }).catch((err) => { if (!disposed) error.value = err.message; });
loadIssues();
</script>

<template>
  <section class="diagnostics-page">
    <div class="view-toolbar"><label class="checkbox-label"><input v-model="testWrite" type="checkbox" :disabled="busy" />测试保存目录临时写入</label><div class="toolbar-actions"><button :disabled="busy" class="primary" @click="action('environment')"><Stethoscope :size="17" />{{ busy ? '检查中…' : '运行环境检查' }}</button><button :disabled="busy || exporting" @click="exportError = ''; exportOpen = true"><Download :size="17" />导出诊断包</button></div></div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div v-if="report" class="diagnostic-summary"><span>{{ report.environment.system }} {{ report.environment.release }} · Python {{ report.environment.python }}</span><span>检查中 {{ report.tasks.checks }} · 录制任务 {{ report.tasks.recordings }} · 视频处理 {{ report.tasks.processing }}</span><time>{{ formatTime(report.checked_at) }}</time></div>
    <div class="table-wrap"><table class="diagnostic-checks"><thead><tr><th>检查项目</th><th>结果</th><th>详情</th></tr></thead><tbody><tr v-for="check in report?.checks || []" :key="check.key"><td>{{ check.label }}</td><td><span class="diagnostic-state" :class="check.status">{{ statusLabel(check.status) }}</span></td><td>{{ check.detail }}</td></tr><tr v-if="!report"><td colspan="3" class="empty-state">尚未执行环境检查</td></tr></tbody></table></div>
    <section class="diagnostic-section"><h2>连接与编码器</h2><div class="diagnostic-tools">
      <div><div class="diagnostic-action"><label class="field">直播间<select v-model="room" aria-label="诊断直播间" :disabled="busy"><option value="">全部直播间</option><option v-for="item in rooms" :key="item.id" :value="item.id">{{ item.remark || item.owner || item.room_id }} · #{{ item.id }}</option></select></label><button :disabled="busy || !room" @click="action('platform')"><Play :size="16" />测试连接</button></div><p v-if="platformResult" class="diagnostic-result" :class="platformResult.status">{{ platformResult.detail }}</p></div>
      <div><div class="diagnostic-action"><label class="field">硬件编码器<select v-model="encoder" aria-label="诊断硬件编码器" :disabled="busy"><option value="">未选择</option><option v-for="item in hardware" :key="item.value" :value="item.value" :disabled="!item.available">{{ item.label }}{{ item.available ? '' : '（未编译支持）' }}</option></select></label><button :disabled="busy || !encoder" @click="action('encoder')"><Play :size="16" />实际编码测试</button></div><p v-if="encoderResult" class="diagnostic-result" :class="encoderResult.status">{{ encoderResult.detail }}</p><p v-if="report?.encoders?.error" class="error-text">{{ report.encoders.error }}</p></div>
    </div></section>
    <section class="diagnostic-section"><div class="view-toolbar"><h2>近期故障事件</h2><button class="icon-button" title="刷新故障事件" aria-label="刷新故障事件" :disabled="issuesBusy" @click="loadIssues"><RefreshCw :size="17" /></button></div><p class="muted">{{ issueScope }}</p><p v-if="issuesError" class="error-banner" role="alert">{{ issuesError }}</p><div v-for="issue in issues" :key="issue.id" class="diagnostic-issue"><div class="runtime-entry-header"><span class="log-level" :class="issue.level.toLowerCase()">{{ issue.level }}</span><time>{{ formatTime(issue.last_seen) }}</time><span class="muted">{{ issue.count }} 次</span><RouterLink :to="{ path: '/runtime-logs', query: { room_id: issue.room_id, processing_job_id: issue.processing_job_id } }" class="diagnostic-link"><FileText :size="16" />相关日志</RouterLink></div><pre class="runtime-message">{{ issue.message }}</pre><p>{{ issue.advice }}</p></div><p v-if="!issues.length && !issuesError" class="empty-state">{{ issuesBusy ? '加载中…' : '暂无警告或错误事件' }}</p></section>
    <ModalDialog v-if="exportOpen" title="导出诊断包" :busy="exporting" @close="exportOpen = false"><form class="modal-body" @submit.prevent="download"><dl class="settings-detail"><dt>内容</dt><dd>report.json：环境检查、录制设置与任务摘要</dd><dd>runtime.jsonl：所选范围内最近 500 条脱敏日志</dd><dd>manifest.txt：内容清单</dd><dt>不包含</dt><dd>Cookie、完整配置、数据库、录制视频</dd><dt>直播间</dt><dd>{{ room ? '#' + room : '全部' }}</dd></dl><label class="field">开始时间<input v-model="start" type="datetime-local" aria-label="导出开始时间" :disabled="exporting" /></label><label class="field">结束时间<input v-model="end" type="datetime-local" aria-label="导出结束时间" :min="start || undefined" :disabled="exporting" /></label><p v-if="exportError" class="error-text" role="alert">{{ exportError }}</p><footer class="modal-actions"><button type="button" :disabled="exporting" @click="exportOpen = false">取消</button><button type="submit" class="primary" :disabled="exporting"><Download :size="16" />{{ exporting ? '导出中…' : '确认导出' }}</button></footer></form></ModalDialog>
  </section>
</template>
