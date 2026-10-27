<script setup>
import { computed, inject, nextTick, onUnmounted, reactive, ref, watch } from 'vue';
import { FolderOpen, RefreshCw, RotateCcw, Save } from '@lucide/vue';
import { api } from '../api.js';
import DirectoryPicker from '../components/DirectoryPicker.vue';
import DiskStatus from '../components/DiskStatus.vue';

const notify = inject('notify');
const presets = [
  { label: '平台 / 主播 / 时间', value: '{platform}_{owner}_{timestamp}' },
  { label: '主播 / 日期 / 时间', value: '{owner}_{date}_{time}' },
  { label: '平台 / 房间号 / 标题 / 时间', value: '{platform}_{room_id}_{title}_{timestamp}' },
  { label: '按主播分目录', value: '{owner}/{timestamp}' },
  { label: '按备注分目录', value: '{remark}/{owner}_{timestamp}' },
];
const tokens = [
  ['platform', '平台'], ['owner', '主播'], ['remark', '备注'], ['room_id', '房间号'], ['title', '标题'],
  ['date', '日期'], ['time', '时间'], ['timestamp', '日期时间'], ['record_id', '唯一编号'],
];
const diskStatus = ref(null);
const draft = reactive({ save_path: '', filename_template: '', check_interval_seconds: 5, disk_protection_enabled: true, disk_min_free_gb: 5, disk_stop_free_gb: 1 });
const saved = ref(null);
const loading = ref(true);
const saving = ref(false);
const loadError = ref('');
const saveError = ref('');
const preview = ref(null);
const previewBusy = ref(false);
const previewError = ref('');
const rule = ref('custom');
const directoryPickerOpen = ref(false);
const directoryBrowseButton = ref(null);
let previewTimer;
let previewId = 0;
let disposed = false;
const dirty = computed(() => saved.value && Object.keys(draft).some((key) => draft[key] !== saved.value[key]));
function applySettings(data) {
  saved.value = { save_path: data.save_path, filename_template: data.filename_template, check_interval_seconds: data.check_interval_seconds,
    disk_protection_enabled: data.disk_protection_enabled ?? true, disk_min_free_gb: data.disk_min_free_gb ?? 5, disk_stop_free_gb: data.disk_stop_free_gb ?? 1 };
  Object.assign(draft, saved.value);
  rule.value = presets.some((item) => item.value === data.filename_template) ? data.filename_template : 'custom';
  preview.value = data;
  previewError.value = '';
}
async function load() {
  loading.value = true;
  loadError.value = '';
  try { const data = await api.settings(); if (!disposed) applySettings(data); }
  catch (error) { if (!disposed) loadError.value = error.message; }
  finally { if (!disposed) loading.value = false; }
}
function selectRule() {
  if (rule.value !== 'custom') draft.filename_template = rule.value;
}
function resetDraft() {
  Object.assign(draft, saved.value);
  rule.value = presets.some((item) => item.value === draft.filename_template) ? draft.filename_template : 'custom';
  saveError.value = '';
}
function selectDirectory(path) {
  draft.save_path = path;
  saveError.value = '';
  closeDirectoryPicker();
}
async function closeDirectoryPicker() {
  directoryPickerOpen.value = false;
  await nextTick();
  if (!disposed) directoryBrowseButton.value?.focus();
}
async function save() {
  if (saving.value || previewBusy.value || previewError.value) return;
  saving.value = true;
  saveError.value = '';
  try {
    const data = await api.saveSettings({ ...draft });
    if (!disposed) { applySettings(data); diskStatus.value?.refresh(); notify('录制设置已保存'); }
  } catch (error) { if (!disposed) saveError.value = error.message; }
  finally { if (!disposed) saving.value = false; }
}
watch(() => [draft.save_path, draft.filename_template], () => {
  if (!saved.value) return;
  clearTimeout(previewTimer);
  const id = ++previewId;
  if (preview.value?.save_path === draft.save_path && preview.value?.filename_template === draft.filename_template) {
    previewBusy.value = false;
    previewError.value = '';
    return;
  }
  previewBusy.value = true;
  previewError.value = '';
  previewTimer = setTimeout(async () => {
    try {
      const data = await api.previewSettings({ save_path: draft.save_path, filename_template: draft.filename_template });
      if (!disposed && id === previewId) preview.value = data;
    } catch (error) { if (!disposed && id === previewId) previewError.value = error.message; }
    finally { if (!disposed && id === previewId) previewBusy.value = false; }
  }, 300);
});
onUnmounted(() => { disposed = true; previewId += 1; clearTimeout(previewTimer); });
load();
</script>

<template>
  <section class="settings-page" :aria-busy="loading">
    <div v-if="loadError" class="error-banner" role="alert">{{ loadError }}<button class="icon-button" title="重试" aria-label="重试加载设置" @click="load"><RefreshCw :size="17" /></button></div>
    <p v-else-if="loading" class="muted">正在加载设置…</p>
    <form v-else @submit.prevent="save">
      <fieldset :disabled="saving" class="settings-fields">
        <section class="settings-section">
          <h2>录制文件</h2>
          <div class="field"><label for="save-path">保存路径</label><div class="save-path-input"><input id="save-path" v-model="draft.save_path" required maxlength="1024" placeholder="./record" /><button ref="directoryBrowseButton" type="button" class="icon-button" title="浏览保存目录" aria-label="浏览保存目录" @click="directoryPickerOpen = true"><FolderOpen :size="19" /></button></div></div>
          <dl class="settings-detail"><dt>后端保存目录</dt><dd>{{ previewBusy ? '计算中…' : previewError ? '-' : preview?.resolved_save_path }}</dd></dl>
          <label class="field">命名规则<select v-model="rule" aria-label="命名规则" @change="selectRule"><option v-for="preset in presets" :key="preset.value" :value="preset.value">{{ preset.label }}</option><option value="custom">自定义</option></select></label>
          <template v-if="rule === 'custom'">
            <label class="field">文件名模板<input v-model="draft.filename_template" required maxlength="255" spellcheck="false" /></label>
            <dl class="template-tokens"><div v-for="[token, label] in tokens" :key="token"><dt>{{ label }}</dt><dd><code>{{ '{' + token + '}' }}</code></dd></div></dl>
          </template>
          <dl class="settings-detail filename-preview" aria-live="polite"><dt>相对路径示例</dt><dd>{{ previewBusy ? '计算中…' : previewError ? '-' : preview?.filename_example }}</dd></dl>
          <p v-if="previewError" class="error-text" role="alert">{{ previewError }}</p>
        </section>
        <section class="settings-section">
          <h2>直播检查</h2>
          <label class="field interval-field">检查周期<div class="input-unit"><input v-model.number="draft.check_interval_seconds" type="number" aria-label="检查周期" required min="1" max="86400" step="1" /><span aria-hidden="true">秒</span></div></label>
        </section>
        <section class="settings-section">
          <h2>磁盘空间保护</h2>
          <DiskStatus ref="diskStatus" />
          <label class="checkbox-label"><input v-model="draft.disk_protection_enabled" type="checkbox" />启用磁盘空间保护</label>
          <div class="disk-thresholds">
            <label class="field">暂停新录制阈值<div class="input-unit"><input v-model.number="draft.disk_min_free_gb" type="number" aria-label="暂停新录制阈值" min="2" max="1048576" step="1" required :disabled="!draft.disk_protection_enabled" /><span>GiB</span></div></label>
            <label class="field">停止录制阈值<div class="input-unit"><input v-model.number="draft.disk_stop_free_gb" type="number" aria-label="停止录制阈值" min="1" :max="draft.disk_min_free_gb - 1" step="1" required :disabled="!draft.disk_protection_enabled" /><span>GiB</span></div></label>
          </div>
        </section>
      </fieldset>
      <p v-if="saveError" class="error-banner" role="alert">{{ saveError }}</p>
      <footer class="settings-actions"><span class="muted">{{ dirty ? '有未保存的修改' : '已保存' }}</span><button type="button" :disabled="!dirty || saving" @click="resetDraft"><RotateCcw :size="16" />还原修改</button><button type="submit" class="primary" :disabled="!dirty || saving || previewBusy || !!previewError"><Save :size="16" />{{ saving ? '保存中…' : '保存设置' }}</button></footer>
    </form>
    <DirectoryPicker v-if="directoryPickerOpen" :initial-path="draft.save_path" @select="selectDirectory" @close="closeDirectoryPicker" />
  </section>
</template>
