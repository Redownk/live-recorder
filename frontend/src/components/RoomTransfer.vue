<script setup>
import { computed, inject, ref } from 'vue';
import { Download, Upload } from '@lucide/vue';
import { api } from '../api.js';
import ModalDialog from './ModalDialog.vue';

defineProps({ disabled: Boolean });
const emit = defineEmits(['imported']);
const notify = inject('notify');
const open = ref(false);
const exporting = ref(false);
const reading = ref(false);
const importing = ref(false);
const backupFile = ref(null);
const preview = ref(null);
const result = ref(null);
const error = ref('');
const filename = ref('');
const enableMonitoring = ref(false);
const page = ref(0);
const summary = computed(() => result.value || preview.value);
const rows = computed(() => (summary.value?.rows || []).slice(page.value * 50, (page.value + 1) * 50));
const busy = computed(() => reading.value || importing.value);
const stateLabels = { new: '可导入', imported: '已导入', duplicate: '重复', invalid: '无效' };

function openImport() {
  backupFile.value = preview.value = result.value = null;
  error.value = filename.value = '';
  enableMonitoring.value = false;
  page.value = 0;
  open.value = true;
}

async function readFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  backupFile.value = preview.value = result.value = null;
  error.value = '';
  filename.value = file.name;
  page.value = 0;
  reading.value = true;
  try {
    if (file.size > 5 * 1024 * 1024) throw new Error('文件不能超过 5 MiB');
    if (!file.name.toLowerCase().endsWith('.xlsx')) throw new Error('请选择 Excel（.xlsx）文件');
    preview.value = await api.previewRoomImport(file);
    backupFile.value = file;
  } catch (err) { error.value = err.message; event.target.value = ''; }
  finally { reading.value = false; }
}

async function importRooms() {
  if (busy.value || !preview.value?.new || result.value) return;
  importing.value = true;
  error.value = '';
  try {
    result.value = await api.importRooms(backupFile.value, enableMonitoring.value);
    page.value = 0;
    notify(`导入完成：新增 ${result.value.imported} 个，重复 ${result.value.duplicate} 个，无效 ${result.value.invalid} 个`);
    emit('imported');
  } catch (err) { error.value = err.message; }
  finally { importing.value = false; }
}

async function exportRooms() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const blob = await api.exportRooms();
    const url = URL.createObjectURL(blob);
    const link = window.document.createElement('a');
    link.href = url;
    link.download = `live-rooms-${new Date().toISOString().replace(/[:.]/g, '-')}.xlsx`;
    window.document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify('直播间列表已导出');
  } catch (err) { notify(err.message, 'error'); }
  finally { exporting.value = false; }
}
</script>

<template>
  <div class="room-transfer-actions">
    <button :disabled="disabled || exporting" @click="openImport"><Upload :size="16" />导入</button>
    <button title="导出全部直播间，不受当前筛选影响" :disabled="disabled || exporting" @click="exportRooms"><Download :size="16" />{{ exporting ? '导出中…' : '导出全部' }}</button>
  </div>
  <ModalDialog v-if="open" title="导入直播间" :busy="busy" @close="open = false">
    <div class="modal-body room-import-body">
      <p class="muted">选择 Excel（.xlsx）文件，第一行包含“平台”和“房间号”。相同平台和房间号会自动跳过。</p>
      <label class="field">直播间 Excel 文件<input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" :disabled="busy" @change="readFile" /></label>
      <p v-if="filename" class="secondary-text">{{ filename }}</p>
      <p v-if="reading" role="status">正在校验文件…</p>
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      <template v-if="summary">
        <p role="status" class="import-summary">共 {{ summary.total }} 条，{{ result ? `已导入 ${summary.imported}` : `可新增 ${summary.new}` }} 条，重复 {{ summary.duplicate }} 条，无效 {{ summary.invalid }} 条。</p>
        <div v-if="rows.length" class="table-wrap import-preview">
          <table aria-label="直播间导入预览"><thead><tr><th>Excel 行号</th><th>直播间</th><th>结果</th></tr></thead>
            <tbody><tr v-for="row in rows" :key="row.row"><td>{{ row.row }}</td><td><strong>{{ row.owner || row.room_id || '-' }}</strong><small class="secondary-text">{{ row.platform }} {{ row.room_id }}</small></td><td><span :class="{ 'error-text': row.status === 'invalid' }">{{ stateLabels[row.status] }}</span><small class="secondary-text">{{ row.message }}</small></td></tr></tbody>
          </table>
        </div>
        <div v-if="summary.rows.length > 50" class="import-pagination"><button :disabled="page === 0" @click="page--">上一页</button><span>第 {{ page + 1 }} / {{ Math.ceil(summary.rows.length / 50) }} 页</span><button :disabled="(page + 1) * 50 >= summary.rows.length" @click="page++">下一页</button></div>
        <label v-if="!result" class="checkbox-label"><input v-model="enableMonitoring" type="checkbox" :disabled="busy" />恢复文件中的监控设置</label>
        <p v-if="!result" class="secondary-text">默认暂停新导入直播间的监控；勾选后，文件中已启用监控的直播间将参与自动录制。</p>
      </template>
      <footer class="modal-actions"><button :disabled="busy" @click="open = false">{{ result ? '关闭' : '取消' }}</button><button v-if="!result" class="primary" :disabled="busy || !preview?.new" @click="importRooms">{{ importing ? '导入中…' : `确认导入${preview?.new ? ` ${preview.new} 个直播间` : ''}` }}</button></footer>
    </div>
  </ModalDialog>
</template>
