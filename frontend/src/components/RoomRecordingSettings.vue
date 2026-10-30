<script setup>
import { computed, inject, nextTick, onUnmounted, reactive, ref, watch } from 'vue';
import { FolderOpen, RefreshCw, RotateCcw, Save } from '@lucide/vue';
import { api } from '../api.js';
import { recordingQualities } from '../recordingOptions.js';
import ModalDialog from './ModalDialog.vue';
import DirectoryPicker from './DirectoryPicker.vue';

const props = defineProps({ room: { type: Object, required: true } });
const emit = defineEmits(['close', 'saved']);
const notify = inject('notify');
const keys = ['save_path', 'filename_template', 'quality', 'check_interval_seconds', 'segment_minutes'];
const values = reactive({ save_path: '', filename_template: '', quality: 'best', check_interval_seconds: 5, segment_minutes: 0 });
const inherit = reactive(Object.fromEntries(keys.map((key) => [key, true])));
const saved = ref(null);
const preview = ref(null);
const loading = ref(true);
const saving = ref(false);
const error = ref('');
const previewError = ref('');
const previewBusy = ref(false);
const pickerOpen = ref(false);
const folderButton = ref(null);
let disposed = false;
let timer;
let previewId = 0;
const payload = () => Object.fromEntries(keys.map((key) => [key, inherit[key] ? null : values[key]]));
const dirty = computed(() => saved.value && keys.some((key) => payload()[key] !== (saved.value.overrides[key] ?? null)));
function apply(data) {
  preview.value = data;
  saved.value = data;
  for (const key of keys) { inherit[key] = data.overrides[key] == null; values[key] = data.effective[key]; }
}
async function load() {
  loading.value = true;
  error.value = '';
  try { const data = await api.roomSettings(props.room.id); if (!disposed) apply(data); }
  catch (err) { if (!disposed) error.value = err.message; }
  finally { if (!disposed) loading.value = false; }
}
function resetAll() { for (const key of keys) inherit[key] = true; }
async function closePicker() { pickerOpen.value = false; await nextTick(); if (!disposed) folderButton.value?.focus(); }
function selectFolder(path) { values.save_path = path; closePicker(); }
async function save() {
  if (saving.value || previewBusy.value || previewError.value) return;
  saving.value = true;
  error.value = '';
  try {
    const data = await api.saveRoomSettings(props.room.id, payload());
    if (!disposed) { notify('房间录制设置已保存'); emit('saved', data); }
  } catch (err) { if (!disposed) error.value = err.message; }
  finally { if (!disposed) saving.value = false; }
}
watch(() => JSON.stringify(payload()), () => {
  if (loading.value || !saved.value) return;
  clearTimeout(timer);
  const id = ++previewId;
  previewBusy.value = true;
  previewError.value = '';
  timer = setTimeout(async () => {
    try {
      const data = await api.previewRoomSettings(props.room.id, payload());
      if (!disposed && id === previewId) {
        preview.value = data;
        for (const key of keys) if (inherit[key]) values[key] = data.effective[key];
      }
    } catch (err) { if (!disposed && id === previewId) previewError.value = err.message; }
    finally { if (!disposed && id === previewId) previewBusy.value = false; }
  }, 300);
});
onUnmounted(() => { disposed = true; previewId += 1; clearTimeout(timer); });
load();
</script>

<template>
  <ModalDialog class="room-settings-dialog" :title="'录制设置 · ' + (room.remark || room.owner || room.room_id)" :busy="saving" @close="emit('close')">
    <div v-if="loading" class="modal-body muted">加载中…</div>
    <div v-else-if="!saved" class="modal-body"><p class="error-text" role="alert">{{ error }}</p><button @click="load"><RefreshCw :size="16" />重试</button></div>
    <form v-else class="modal-body room-settings-body" @submit.prevent="save">
      <div class="room-settings-content">
      <fieldset :disabled="saving" class="settings-fields room-overrides">
        <div class="room-override"><div class="override-heading"><label for="room-save-path">保存目录</label><label class="checkbox-label"><input v-model="inherit.save_path" type="checkbox" aria-label="继承全局保存目录" />继承全局</label></div><div class="save-path-input"><input id="room-save-path" v-model="values.save_path" maxlength="1024" required :disabled="inherit.save_path" /><button ref="folderButton" class="icon-button" type="button" title="浏览房间保存目录" aria-label="浏览房间保存目录" :disabled="inherit.save_path" @click="pickerOpen = true"><FolderOpen :size="18" /></button></div></div>
        <div class="room-override"><div class="override-heading"><label for="room-filename-template">命名规则</label><label class="checkbox-label"><input v-model="inherit.filename_template" type="checkbox" aria-label="继承全局命名规则" />继承全局</label></div><input id="room-filename-template" v-model="values.filename_template" maxlength="255" required spellcheck="false" :disabled="inherit.filename_template" /></div>
        <div class="room-override"><div class="override-heading"><label for="room-quality">清晰度</label><label class="checkbox-label"><input v-model="inherit.quality" type="checkbox" aria-label="继承全局清晰度" />继承全局</label></div><select id="room-quality" v-model="values.quality" :disabled="inherit.quality"><option v-for="item in recordingQualities" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
        <div class="room-override"><div class="override-heading"><label for="room-check-interval">检查周期</label><label class="checkbox-label"><input v-model="inherit.check_interval_seconds" type="checkbox" aria-label="继承全局检查周期" />继承全局</label></div><div class="input-unit"><input id="room-check-interval" v-model.number="values.check_interval_seconds" type="number" required min="1" max="86400" step="1" :disabled="inherit.check_interval_seconds" /><span>秒</span></div></div>
        <div class="room-override"><div class="override-heading"><label for="room-segment-minutes">分片时长</label><label class="checkbox-label"><input v-model="inherit.segment_minutes" type="checkbox" aria-label="继承全局分片时长" />继承全局</label></div><div class="input-unit"><input id="room-segment-minutes" v-model.number="values.segment_minutes" type="number" required min="0" max="1440" step="1" :disabled="inherit.segment_minutes" /><span>分钟</span></div></div>
      </fieldset>
      <div class="room-effective"><span class="muted">下次录制生效</span><dl class="settings-detail"><dt>保存目录</dt><dd>{{ previewBusy ? '计算中…' : previewError ? '-' : preview.resolved_save_path }}</dd><dt>相对路径示例</dt><dd>{{ previewBusy ? '计算中…' : previewError ? '-' : preview.filename_example }}</dd><dt>文件策略</dt><dd>{{ preview.effective.segment_minutes ? preview.effective.segment_minutes + ' 分钟独立分片' : '不定时分片，结束后合并断流分片' }}</dd></dl></div>
      <p v-if="previewError" class="error-text" role="alert">{{ previewError }}</p><p v-if="error" class="error-text" role="alert">{{ error }}</p>
      </div>
      <footer class="modal-actions room-settings-actions"><button type="button" :disabled="saving" @click="resetAll"><RotateCcw :size="16" />全部继承全局</button><button type="button" :disabled="saving" @click="emit('close')">取消</button><button type="submit" class="primary" :disabled="!dirty || saving || previewBusy || !!previewError"><Save :size="16" />{{ saving ? '保存中…' : '保存设置' }}</button></footer>
    </form>
  </ModalDialog>
  <DirectoryPicker v-if="pickerOpen" :initial-path="values.save_path" @select="selectFolder" @close="closePicker" />
</template>
