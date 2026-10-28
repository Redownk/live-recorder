<script setup>
import { useRoute } from 'vue-router';
import { Stethoscope, X } from '@lucide/vue';
import RuntimeLogPanel from '../components/RuntimeLogPanel.vue';
const route = useRoute();
const number = (value) => /^[1-9]\d*$/.test(value || '') ? Number(value) : undefined;
</script>

<template>
  <section>
    <div class="view-toolbar"><RouterLink v-if="Object.keys(route.query).length" to="/runtime-logs" class="filter-clear"><X :size="15" />清除关联筛选</RouterLink><span v-if="route.query.recording_log_id" class="muted">录制记录 #{{ route.query.recording_log_id }}</span><span v-if="route.query.processing_job_id" class="muted">处理任务 {{ route.query.processing_job_id }}</span><RouterLink class="diagnostic-link" to="/diagnostics"><Stethoscope :size="17" />故障诊断</RouterLink></div>
    <RuntimeLogPanel :key="route.fullPath" :room-id="number(route.query.room_id)" :recording-log-id="number(route.query.recording_log_id)" :processing-job-id="route.query.processing_job_id" :initial-keyword="route.query.keyword" />
  </section>
</template>
