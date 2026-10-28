<script setup>
import { inject, nextTick, onUnmounted, ref } from 'vue';
import { Copy, Pause, Play, RefreshCw, Search } from '@lucide/vue';
import { api } from '../api.js';
import { formatTime, platformName } from '../format.js';

const props = defineProps({ roomId: Number, recordingLogId: Number, processingJobId: String, initialKeyword: String, compact: Boolean });
const notify = inject('notify');
const entries = ref([]);
const rooms = ref([]);
const room = ref(props.roomId || '');
const platform = ref('');
const level = ref('');
const keyword = ref(props.initialKeyword || '');
const start = ref('');
const end = ref('');
const filters = ref({});
const automatic = ref(true);
const follow = ref(true);
const busy = ref(false);
const error = ref('');
const warning = ref('');
const more = ref(false);
const list = ref(null);
let cursor = '';
let before = '';
let disposed = false;
let generation = 0;
let controller;

function parameters() {
  return { room_id: props.compact ? props.roomId : room.value || undefined, recording_log_id: props.recordingLogId,
    processing_job_id: props.processingJobId, platform: platform.value || undefined, level: level.value || undefined,
    keyword: keyword.value.trim() || undefined, start: start.value ? new Date(start.value).toISOString() : undefined,
    end: end.value ? new Date(end.value).toISOString() : undefined };
}
async function load(mode = 'reset') {
  if (disposed || (busy.value && mode !== 'reset')) return;
  if (mode === 'live' && !cursor) mode = 'reset';
  if (mode === 'reset') { controller?.abort(); generation += 1; entries.value = []; cursor = ''; before = ''; more.value = false; }
  const id = generation;
  controller = new AbortController();
  busy.value = true;
  error.value = '';
  const height = list.value?.scrollHeight || 0;
  const top = list.value?.scrollTop || 0;
  try {
    const data = await api.runtimeLogs({ ...filters.value, ...(mode === 'live' && cursor ? { after: cursor } : {}), ...(mode === 'older' && before ? { before } : {}), limit: 200 }, controller.signal);
    if (disposed || id !== generation) return;
    const combined = new Map([...entries.value, ...(data.entries || [])].map((entry) => [entry.id, entry]));
    entries.value = [...combined.values()].sort((a, b) => b.id.localeCompare(a.id)).slice(0, 1000);
    if (mode !== 'older') cursor = data.cursor || cursor;
    if (mode !== 'live') { before = data.next_before || before; more.value = data.has_more; }
    warning.value = [data.write_error, data.dropped ? `日志队列丢弃 ${data.dropped} 条` : ''].filter(Boolean).join('；');
    await nextTick();
    if (list.value && mode !== 'older') list.value.scrollTop = follow.value ? 0 : top + list.value.scrollHeight - height;
  } catch (err) { if (!disposed && id === generation) error.value = err.message; }
  finally { if (!disposed && id === generation) busy.value = false; }
}
function search() {
  try { filters.value = parameters(); load(); }
  catch { error.value = '时间范围无效'; }
}
function onScroll() { if ((list.value?.scrollTop || 0) > 20) follow.value = false; }
async function copy(entry) {
  try {
    await navigator.clipboard.writeText(`${entry.timestamp} ${entry.level} ${entry.logger}\n${entry.message}${entry.traceback ? '\n' + entry.traceback : ''}`);
    if (!disposed) notify('日志已复制');
  } catch { if (!disposed) notify('无法复制，请检查浏览器剪贴板权限', 'error'); }
}
const poll = setInterval(() => { if (automatic.value) load('live'); }, 2000);
onUnmounted(() => { disposed = true; generation += 1; controller?.abort(); clearInterval(poll); });
if (!props.compact) api.rooms().then((data) => { if (!disposed) rooms.value = data; }).catch(() => {});
search();
</script>

<template>
  <div class="runtime-log-panel" :class="{ compact }">
    <form class="runtime-filters" @submit.prevent="search">
      <label v-if="!compact" class="field">直播间<select v-model="room" aria-label="日志直播间"><option value="">全部直播间</option><option v-for="item in rooms" :key="item.id" :value="item.id">{{ item.remark || item.owner || item.room_id }} · #{{ item.id }}</option></select></label>
      <label v-if="!compact" class="field">平台<select v-model="platform" aria-label="日志平台"><option value="">全部平台</option><option value="DOUYIN">抖音</option><option value="BILIBILI">哔哩哔哩</option><option value="DOUYU">斗鱼</option></select></label>
      <label class="field">级别<select v-model="level" aria-label="日志级别"><option value="">全部级别</option><option v-for="item in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']" :key="item">{{ item }}</option></select></label>
      <label class="field runtime-keyword">关键词<input v-model="keyword" type="search" aria-label="日志关键词" maxlength="200" /></label>
      <button type="submit" class="icon-button" title="筛选日志" aria-label="筛选日志"><Search :size="18" /></button>
      <template v-if="!compact"><label class="field">开始时间<input v-model="start" type="datetime-local" aria-label="日志开始时间" /></label><label class="field">结束时间<input v-model="end" type="datetime-local" aria-label="日志结束时间" /></label></template>
    </form>
    <div class="runtime-toolbar">
      <span class="muted">{{ entries.length }} 条{{ entries.length >= 1000 ? '（显示上限）' : '' }}</span>
      <label class="checkbox-label"><input v-model="follow" type="checkbox" />跟随最新</label>
      <button class="icon-button" :title="automatic ? '暂停刷新' : '恢复刷新'" :aria-label="automatic ? '暂停日志刷新' : '恢复日志刷新'" :aria-pressed="!automatic" @click="automatic = !automatic"><Pause v-if="automatic" :size="18" /><Play v-else :size="18" /></button>
      <button class="icon-button" title="刷新日志" aria-label="刷新运行日志" :disabled="busy" @click="load()"><RefreshCw :size="18" :class="{ spinning: busy }" /></button>
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <p v-if="warning" class="error-banner" role="alert">{{ warning }}</p>
    <div ref="list" class="runtime-list" :aria-busy="busy" @scroll="onScroll">
      <article v-for="entry in entries" :key="entry.id" class="runtime-entry" :class="entry.level.toLowerCase()">
        <div class="runtime-entry-header"><time>{{ formatTime(entry.timestamp) }}</time><span class="log-level">{{ entry.level }}</span><span class="runtime-source">{{ entry.logger }}</span><span v-if="entry.platform" class="muted">{{ platformName(entry.platform) }}</span><span v-if="!compact && entry.room_id" class="muted">房间 #{{ entry.room_id }}</span><span v-if="entry.truncated" class="muted">内容已截断</span><button class="icon-button" title="复制日志" :aria-label="`复制日志 ${entry.id}`" @click="copy(entry)"><Copy :size="15" /></button></div>
        <pre class="runtime-message">{{ entry.message }}</pre>
        <details v-if="entry.traceback" class="runtime-trace"><summary>异常堆栈</summary><pre>{{ entry.traceback }}</pre></details>
      </article>
      <p v-if="!entries.length" class="empty-state">{{ busy ? '日志加载中…' : error ? '日志加载失败' : '暂无匹配日志' }}</p>
      <div v-if="more" class="runtime-pagination"><button :disabled="busy || entries.length >= 1000" @click="load('older')">加载更早日志</button></div>
    </div>
  </div>
</template>
