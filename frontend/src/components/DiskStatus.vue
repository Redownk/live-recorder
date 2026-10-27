<script setup>
import { computed, onUnmounted, ref } from 'vue';
import { HardDrive } from '@lucide/vue';
import { api } from '../api.js';
import { formatBytes } from '../format.js';

const props = defineProps({ compact: Boolean });
const report = ref(null);
const error = ref('');
let busy = false;
let disposed = false;
const disks = computed(() => (report.value?.disks || []).filter((disk) => !props.compact || !['normal', 'disabled'].includes(disk.state)));
async function refresh() {
  if (busy || disposed) return;
  busy = true;
  try {
    const data = await api.diskStatus();
    if (!disposed) { report.value = data; error.value = ''; }
  } catch (err) { if (!disposed) error.value = err.message; }
  finally { busy = false; }
}
defineExpose({ refresh });
const poll = setInterval(refresh, 5000);
onUnmounted(() => { disposed = true; clearInterval(poll); });
refresh();
</script>

<template>
  <p v-if="error" class="error-text" role="status">磁盘容量暂不可用：{{ error }}</p>
  <div v-for="disk in disks" v-else :key="disk.path" class="disk-status" :class="disk.state" :role="['warning', 'critical', 'unavailable'].includes(disk.state) ? 'alert' : 'status'">
    <HardDrive :size="18" aria-hidden="true" />
    <div><strong v-if="disk.free_bytes !== null">剩余 {{ formatBytes(disk.free_bytes) }} / {{ formatBytes(disk.total_bytes) }}</strong><span>{{ disk.message }}</span><span class="disk-path">{{ disk.path }}</span></div>
  </div>
</template>
