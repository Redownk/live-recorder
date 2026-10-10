<script setup>
import { ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Film, RefreshCw, X } from '@lucide/vue';
import { api } from '../api.js';
import { formatDuration, formatTime, platformName } from '../format.js';

const route = useRoute();
const logs = ref([]);
const loading = ref(false);
const error = ref('');
let loadId = 0;
async function load() {
  const id = ++loadId;
  loading.value = true;
  error.value = '';
  try {
    const data = await api.logs({ room_id: route.query.room_id });
    if (id === loadId) logs.value = data;
  } catch (err) { if (id === loadId) error.value = err.message; }
  finally { if (id === loadId) loading.value = false; }
}
watch(() => route.query.room_id, load, { immediate: true });
</script>

<template>
  <section>
    <div class="view-toolbar"><span class="muted">最近 100 条录制日志</span><div class="toolbar-actions"><RouterLink v-if="route.query.room_id" to="/logs" class="filter-clear"><X :size="15" />房间 #{{ route.query.room_id }}</RouterLink><button class="icon-button" title="刷新日志" aria-label="刷新日志" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button></div></div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div class="table-wrap" :aria-busy="loading"><table>
      <thead><tr><th>平台</th><th>主播</th><th>标题</th><th>开始</th><th>结束</th><th>时长</th><th>在线峰值</th><th>视频</th></tr></thead>
      <tbody><tr v-for="log in logs" :key="log.id">
        <td><span class="platform-badge" :class="log.platform.toLowerCase()">{{ platformName(log.platform) }}</span></td><td>{{ log.owner || '-' }}</td><td class="title-cell">{{ log.title || '-' }}</td>
        <td class="time-cell">{{ formatTime(log.start_live) }}</td><td class="time-cell">{{ log.end_live ? formatTime(log.end_live) : '录制中' }}</td><td>{{ formatDuration(log.live_time) }}</td><td>{{ log.user_num ?? '-' }}</td>
        <td><RouterLink class="icon-button" :to="{ path: '/videos', query: { log_id: log.id } }" title="查看视频" :aria-label="`查看日志 ${log.id} 的视频`"><Film :size="17" /></RouterLink></td>
      </tr><tr v-if="!logs.length"><td colspan="8" class="empty-state">{{ loading ? '加载中…' : error ? '日志加载失败' : '暂无录制日志' }}</td></tr></tbody>
    </table></div>
    <p class="list-count">{{ logs.length }} 条日志</p>
  </section>
</template>
