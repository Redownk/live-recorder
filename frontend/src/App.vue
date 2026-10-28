<script setup>
import { computed, onMounted, onUnmounted, provide, ref } from 'vue';
import { useRoute } from 'vue-router';
import { CircleStop, Clapperboard, FileText, Film, ListVideo, Play, Radio, Settings, Stethoscope, WandSparkles, X } from '@lucide/vue';
import { api } from './api.js';

const route = useRoute();
const running = ref(null);
const crawlerBusy = ref(false);
const crawlerAction = ref('');
const crawlerError = ref('');
const toast = ref(null);
let toastTimer;
let pollTimer;
let disposed = false;
const statusText = computed(() => crawlerBusy.value && crawlerAction.value === 'stop' ? '正在停止录制…' : running.value === null ? '状态未知' : running.value ? '监控运行中' : '监控已停止');
function notify(message, kind = 'success') {
  clearTimeout(toastTimer);
  toast.value = { message, kind };
  toastTimer = setTimeout(() => { toast.value = null; }, 5000);
}
provide('notify', notify);
async function refreshStatus() {
  try {
    const data = await api.crawlerStatus();
    if (!disposed) { running.value = data.running; crawlerError.value = ''; }
  } catch (error) {
    if (!disposed) { running.value = null; crawlerError.value = error.message; }
  }
}
async function controlCrawler(action) {
  crawlerBusy.value = true;
  crawlerAction.value = action;
  try {
    await api.crawler(action);
    await refreshStatus();
    notify(action === 'start' ? '监控已启动' : '监控已停止');
  } catch (error) { notify(error.message, 'error'); }
  finally { crawlerBusy.value = false; crawlerAction.value = ''; }
}
onMounted(() => {
  refreshStatus();
  pollTimer = setInterval(() => { if (!crawlerBusy.value) refreshStatus(); }, 10000);
});
onUnmounted(() => { disposed = true; clearInterval(pollTimer); clearTimeout(toastTimer); });
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink to="/rooms" class="brand"><Radio :size="27" /><span>Live Recorder</span></RouterLink>
      <nav aria-label="主导航">
        <RouterLink to="/rooms"><ListVideo :size="19" />直播间</RouterLink>
        <RouterLink to="/logs"><Clapperboard :size="19" />录制日志</RouterLink>
        <RouterLink to="/videos"><Film :size="19" />视频文件</RouterLink>
        <RouterLink to="/runtime-logs"><FileText :size="19" />运行日志</RouterLink>
        <RouterLink to="/diagnostics"><Stethoscope :size="19" />故障诊断</RouterLink>
        <RouterLink to="/processing/transcode" :class="{ 'router-link-active': route.path.startsWith('/processing') }"><WandSparkles :size="19" />视频处理</RouterLink>
        <RouterLink to="/settings"><Settings :size="19" />设置</RouterLink>
      </nav>
      <section class="crawler-panel" aria-label="录制监控">
        <p class="section-label">录制监控</p>
        <p class="crawler-status"><span class="status-dot" :class="{ running: running === true }"></span>{{ statusText }}</p>
        <p v-if="crawlerError" class="error-text">{{ crawlerError }}</p>
        <div class="crawler-actions">
          <button :disabled="crawlerBusy || running === true" @click="controlCrawler('start')"><Play :size="16" />启动</button>
          <button :disabled="crawlerBusy || running === false" title="停止监控和录制" @click="controlCrawler('stop')"><CircleStop :size="16" />停止</button>
        </div>
      </section>
    </aside>
    <main class="main-content">
      <header class="page-header"><h1>{{ route.meta.title }}</h1><span class="header-tag">LIVE RECORDER</span></header>
      <RouterView />
    </main>
    <div v-if="toast" class="toast" :class="toast.kind" role="status" aria-live="polite">
      <span>{{ toast.message }}</span>
      <button class="icon-button" title="关闭通知" aria-label="关闭通知" @click="toast = null"><X :size="16" /></button>
    </div>
  </div>
</template>
