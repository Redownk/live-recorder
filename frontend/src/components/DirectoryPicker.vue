<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ArrowRight, ArrowUp, Check, ChevronLeft, ChevronRight, FileVideo, Folder, HardDrive, RefreshCw } from '@lucide/vue';
import { api } from '../api.js';
import ModalDialog from './ModalDialog.vue';

const props = defineProps({ initialPath: { type: String, default: '' }, files: Boolean });
const emit = defineEmits(['close', 'select']);
const data = ref(null);
const pathInput = ref(props.initialPath);
const loading = ref(false);
const error = ref('');
const selected = ref([]);
let requestId = 0;
let disposed = false;
const canSelect = computed(() => !loading.value && !error.value && (props.files ? selected.value.length > 0 : !!data.value?.path && pathInput.value.trim() === data.value.path));
const pageRange = computed(() => data.value?.total ? `${data.value.offset + 1}–${Math.min(data.value.offset + data.value.limit, data.value.total)} / ${data.value.total}` : '0');

async function browse(path, offset = 0) {
  const id = ++requestId;
  loading.value = true;
  error.value = '';
  try {
    const result = await (props.files ? api.processingFiles : api.directories)({ path: path || undefined, offset });
    if (!disposed && id === requestId) {
      data.value = result;
      pathInput.value = result.path || '';
    }
  } catch (err) { if (!disposed && id === requestId) error.value = err.message; }
  finally { if (!disposed && id === requestId) loading.value = false; }
}
function select() {
  if (canSelect.value) emit('select', props.files ? selected.value : data.value.path);
}
function toggleFile(path) {
  selected.value = selected.value.includes(path) ? selected.value.filter((item) => item !== path) : [...selected.value, path];
}
onMounted(() => browse(props.initialPath));
onUnmounted(() => { disposed = true; requestId += 1; });
</script>

<template>
  <ModalDialog :title="files ? '选择视频文件' : '选择保存目录'" class="directory-dialog" @close="emit('close')">
    <div class="directory-body">
      <div class="directory-toolbar">
        <button type="button" class="icon-button" title="盘符和根目录" aria-label="盘符和根目录" @click="browse()"><HardDrive :size="18" /></button>
        <button type="button" class="icon-button" title="上一级" aria-label="上一级" :disabled="loading || !data?.path" @click="browse(data.parent)"><ArrowUp :size="18" /></button>
        <button type="button" class="icon-button" title="刷新目录" aria-label="刷新目录" :disabled="loading" @click="browse(data?.path || pathInput, data?.offset || 0)"><RefreshCw :size="17" :class="{ spinning: loading }" /></button>
        <span class="directory-source">后端本机目录</span>
      </div>
      <form class="directory-location" @submit.prevent="browse(pathInput.trim())">
        <input v-model="pathInput" aria-label="当前目录" maxlength="1024" placeholder="目录路径" autocomplete="off" spellcheck="false" />
        <button type="submit" class="icon-button" title="打开目录" aria-label="打开目录" :disabled="loading"><ArrowRight :size="18" /></button>
      </form>
      <div v-if="data?.shortcuts" class="directory-shortcuts">
        <button v-for="shortcut in data.shortcuts" :key="shortcut.path" type="button" @click="browse(shortcut.path)"><Folder :size="15" />{{ shortcut.name }}</button>
      </div>
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      <div class="directory-list" :aria-busy="loading" :aria-label="files ? '目录和视频文件' : '子目录'">
        <p v-if="loading" class="directory-empty muted">正在加载目录…</p>
        <template v-else-if="!error">
          <template v-for="entry in data?.directories || []" :key="entry.path">
            <label v-if="entry.is_file" class="directory-entry file-entry"><FileVideo :size="19" /><span>{{ entry.name }}</span><input type="checkbox" :aria-label="`选择 ${entry.name}`" :checked="selected.includes(entry.path)" @change="toggleFile(entry.path)" /></label>
            <button v-else type="button" class="directory-entry" :aria-label="`打开 ${entry.name}`" @click="browse(entry.path)"><Folder v-if="data.path" :size="19" /><HardDrive v-else :size="19" /><span>{{ entry.name }}</span><ChevronRight :size="16" /></button>
          </template>
          <p v-if="!data?.directories.length" class="directory-empty muted">{{ files ? '没有视频文件或子目录' : '没有子目录' }}</p>
        </template>
      </div>
      <div class="directory-pagination">
        <span class="muted">{{ pageRange }} 项</span>
        <button type="button" class="icon-button" title="上一页" aria-label="上一页目录" :disabled="loading || !!error || !data?.offset" @click="browse(data.path, Math.max(0, data.offset - data.limit))"><ChevronLeft :size="17" /></button>
        <button type="button" class="icon-button" title="下一页" aria-label="下一页目录" :disabled="loading || !!error || !data?.has_more" @click="browse(data.path, data.offset + data.limit)"><ChevronRight :size="17" /></button>
      </div>
      <dl class="directory-selection"><dt>{{ files ? '已选文件' : '选定目录' }}</dt><dd>{{ files ? `${selected.length} 个` : canSelect ? data.path : '-' }}</dd></dl>
      <footer class="modal-actions"><button type="button" @click="emit('close')">取消</button><button type="button" class="primary" :disabled="!canSelect" @click="select"><Check :size="16" />{{ files ? '添加所选文件' : '选择此目录' }}</button></footer>
    </div>
  </ModalDialog>
</template>
