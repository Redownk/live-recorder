<script setup>
import { ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ExternalLink, RefreshCw, X } from '@lucide/vue';
import { api } from '../api.js';
import { formatBytes, formatDuration, formatTime, safeUrl } from '../format.js';

const route = useRoute();
const videos = ref([]);
const loading = ref(false);
const error = ref('');
const videoUrl = (video) => video.file_path ? api.videoFileUrl(video.id) : safeUrl(video.file_url);
let loadId = 0;
async function load() {
  const id = ++loadId;
  loading.value = true;
  error.value = '';
  try {
    const data = await api.videos({ log_id: route.query.log_id });
    if (id === loadId) videos.value = data;
  } catch (err) { if (id === loadId) error.value = err.message; }
  finally { if (id === loadId) loading.value = false; }
}
watch(() => route.query.log_id, load, { immediate: true });
</script>

<template>
  <section>
    <div class="view-toolbar"><span class="muted">最近 100 个视频文件</span><div class="toolbar-actions"><RouterLink v-if="route.query.log_id" to="/videos" class="filter-clear"><X :size="15" />日志 #{{ route.query.log_id }}</RouterLink><button class="icon-button" title="刷新视频" aria-label="刷新视频" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button></div></div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div class="table-wrap" :aria-busy="loading"><table>
      <thead><tr><th>文件名</th><th>大小</th><th>时长</th><th>创建时间</th><th>地址</th></tr></thead>
      <tbody><tr v-for="video in videos" :key="video.id"><td class="filename-cell">{{ video.file_name }}</td><td>{{ formatBytes(video.file_size) }}</td><td>{{ formatDuration(video.duration) }}</td><td class="time-cell">{{ formatTime(video.create_time) }}</td><td><a v-if="videoUrl(video)" :href="videoUrl(video)" class="icon-button" target="_blank" rel="noopener noreferrer" title="打开视频" :aria-label="`打开 ${video.file_name}`"><ExternalLink :size="17" /></a><span v-else class="muted">-</span></td></tr><tr v-if="!videos.length"><td colspan="5" class="empty-state">{{ loading ? '加载中…' : error ? '视频加载失败' : '暂无视频文件' }}</td></tr></tbody>
    </table></div>
    <p class="list-count">{{ videos.length }} 个文件</p>
  </section>
</template>
