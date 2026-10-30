<script setup>
import { inject, nextTick, onUnmounted, ref, watch } from 'vue';
import { Check, FileText, History, Pencil, Play, Plus, Radio, RefreshCw, Search, SlidersHorizontal, Square, Trash2, X } from '@lucide/vue';
import { api } from '../api.js';
import { formatBytes, formatDuration, formatTime, platformName, safeUrl } from '../format.js';
import ModalDialog from '../components/ModalDialog.vue';
import DiskStatus from '../components/DiskStatus.vue';
import RuntimeLogPanel from '../components/RuntimeLogPanel.vue';
import RoomRecordingSettings from '../components/RoomRecordingSettings.vue';

const notify = inject('notify');
const rooms = ref([]);
const keyword = ref('');
const loading = ref(false);
const error = ref('');
const modal = ref(null);
const selected = ref(null);
const saving = ref(false);
const formError = ref('');
const rowBusy = ref([]);
const startBusy = ref([]);
const disableMonitor = ref(true);
const logRoom = ref(null);
const settingsRoom = ref(null);
let settingsButton;
function openRoomSettings(room, event) { settingsRoom.value = room; settingsButton = event.currentTarget; }
async function closeRoomSettings() { settingsRoom.value = null; await nextTick(); if (!disposed) settingsButton?.focus(); }
function roomSettingsSaved(data) { const room = rooms.value.find((item) => item.id === data.room_id); if (room) room.recording_settings_customized = data.customized; closeRoomSettings(); }
let logButton;
function openLogs(room, event) { logRoom.value = room; logButton = event.currentTarget; }
async function closeLogs() { logRoom.value = null; await nextTick(); if (!disposed) logButton?.focus(); }
const statuses = ref({});
const statusLoaded = ref(false);
const statusError = ref('');
const statusTick = ref(performance.now());
let statusReceivedAt = performance.now();
let statusBusy = false;
let disposed = false;
const draft = ref({});
const remarkEditingId = ref(null);
const remarkDraft = ref('');
const remarkSaving = ref(false);
const remarkError = ref('');
const remarkInput = ref(null);
let loadId = 0;

async function loadRecordingStatus() {
  if (statusBusy || disposed) return;
  statusBusy = true;
  try {
    const data = await api.recordingStatuses();
    if (!disposed) {
      statuses.value = data;
      for (const room of rooms.value) {
        if (data[room.id]?.monitor_enabled === false) room.monitor_enabled = false;
      }
      statusReceivedAt = performance.now();
      statusTick.value = statusReceivedAt;
      statusLoaded.value = true;
      statusError.value = '';
    }
  } catch (err) { if (!disposed) statusError.value = err.message; }
  finally { statusBusy = false; }
}
function recordingLabel(room) {
  if (statusError.value) return '状态不可用';
  if (!statusLoaded.value) return '获取中…';
  return { recording: '录制中', reconnecting: '重连中', checking: '检查中', preparing: '准备中', finishing: '结束中', merging: '合并中', registering: '保存中', stopping: '停止中', disk_blocked: '空间不足', health_failed: '健康异常' }[statuses.value[room.id]?.state] || '未录制';
}
function healthLabel(room) {
  if (statusError.value) return '-';
  const status = statuses.value[room.id];
  if (status?.state === 'health_failed') return '已暂停监控';
  return { healthy: '正常', starting: '启动中', waiting: '等待数据', recovering: '自动恢复中', disabled: '已关闭' }[status?.health?.state] || '-';
}
function recordingDuration(room) {
  const status = statuses.value[room.id];
  if (statusError.value || !statusLoaded.value || !['recording', 'reconnecting'].includes(status?.state)) return '-';
  return formatDuration(status.elapsed_seconds + Math.max(0, statusTick.value - statusReceivedAt) / 1000);
}

async function loadRooms() {
  const id = ++loadId;
  loading.value = true;
  error.value = '';
  try {
    const data = await api.rooms({ keyword: keyword.value.trim() });
    if (id === loadId) rooms.value = data;
  } catch (err) { if (id === loadId) error.value = err.message; }
  finally { if (id === loadId) loading.value = false; }
}
async function refreshRooms() {
  await Promise.all([loadRooms(), loadRecordingStatus()]);
}
function openModal(type, room = null) {
  if (remarkSaving.value) return;
  cancelRemark();
  selected.value = room;
  formError.value = '';
  disableMonitor.value = true;
  draft.value = type === 'edit'
    ? { owner: room.owner || '', title: room.title || '', remark: room.remark || '', monitor_enabled: room.monitor_enabled }
    : { room_url: '', remark: '', monitor_enabled: true };
  modal.value = type;
}
async function saveRoom() {
  if (saving.value) return;
  saving.value = true;
  formError.value = '';
  try {
    const payload = { ...draft.value, remark: draft.value.remark.trim() || null };
    if (modal.value === 'add') await api.addRoom({ ...payload, room_url: draft.value.room_url.trim() });
    else await api.editRoom(selected.value.id, payload);
    notify(modal.value === 'add' ? '直播间已添加' : '直播间已更新');
    modal.value = null;
    await loadRooms();
  } catch (err) { formError.value = err.message; }
  finally { saving.value = false; }
}
async function removeRoom() {
  if (saving.value) return;
  saving.value = true;
  try {
    await api.deleteRoom(selected.value.id);
    modal.value = null;
    notify('直播间已删除');
    await loadRooms();
  } catch (err) { formError.value = err.message; }
  finally { saving.value = false; }
}
async function startRecording(room) {
  if (startBusy.value.includes(room.id)) return;
  startBusy.value.push(room.id);
  try {
    const result = await api.startRecording(room.id);
    if (!disposed) notify({ started: '已提交录制任务', offline: '当前未开播', busy: '已有检查或录制任务', stopped: '录制请求已停止' }[result.status] || '操作完成');
  } catch (err) { if (!disposed) notify(err.message, 'error'); }
  finally {
    startBusy.value = startBusy.value.filter((id) => id !== room.id);
    await loadRecordingStatus();
  }
}
async function stopRecording() {
  if (saving.value) return;
  saving.value = true;
  formError.value = '';
  try {
    await api.stopRecording(selected.value.id, disableMonitor.value);
    modal.value = null;
    notify(disableMonitor.value ? '录制已停止，监控已暂停' : '本次录制已停止');
    await refreshRooms();
  } catch (err) { formError.value = err.message; }
  finally { saving.value = false; }
}
async function roomAction(room, action, event) {
  if (rowBusy.value.includes(room.id)) return;
  rowBusy.value.push(room.id);
  try {
    if (action === 'check') {
      const result = await api.liveStatus(room.id);
      notify(result.is_live ? `正在直播：${result.title || result.owner || ''}` : '当前未开播');
    } else {
      const updated = await api.monitor(room.id, !room.monitor_enabled);
      Object.assign(room, updated);
      await loadRecordingStatus();
    }
  } catch (err) { notify(err.message, 'error'); }
  finally {
    if (event) event.target.checked = room.monitor_enabled;
    rowBusy.value = rowBusy.value.filter((id) => id !== room.id);
  }
}
function setRemarkInput(element) { remarkInput.value = element; }
async function editRemark(room) {
  if (remarkSaving.value) return;
  remarkEditingId.value = room.id;
  remarkDraft.value = room.remark || '';
  remarkError.value = '';
  await nextTick();
  remarkInput.value?.focus();
}
function cancelRemark() {
  if (remarkSaving.value) return;
  remarkEditingId.value = null;
  remarkError.value = '';
}
async function saveRemark(room) {
  if (remarkSaving.value) return;
  remarkSaving.value = true;
  remarkError.value = '';
  try {
    const updated = await api.editRoom(room.id, { remark: remarkDraft.value.trim() || null });
    rooms.value = rooms.value.map((item) => item.id === room.id ? { ...item, ...updated } : item);
    remarkEditingId.value = null;
    notify('备注已保存');
  } catch (err) { remarkError.value = err.message; }
  finally { remarkSaving.value = false; }
}
watch(keyword, (value) => { if (!value) loadRooms(); });
const statusPoll = setInterval(loadRecordingStatus, 3000);
const durationTick = setInterval(() => { statusTick.value = performance.now(); }, 1000);
onUnmounted(() => {
  disposed = true;
  loadId += 1;
  clearInterval(statusPoll);
  clearInterval(durationTick);
});
loadRooms();
loadRecordingStatus();
</script>

<template>
  <section>
    <div class="view-toolbar">
      <form class="search-form" role="search" @submit.prevent="loadRooms">
        <Search :size="17" /><input v-model="keyword" type="search" aria-label="搜索直播间" placeholder="搜索房间、主播、备注、标题" />
        <button type="submit" class="icon-button" title="搜索" aria-label="搜索"><Search :size="17" /></button>
      </form>
      <div class="toolbar-actions">
        <button class="icon-button" title="刷新直播间" aria-label="刷新直播间" :disabled="loading" @click="refreshRooms"><RefreshCw :size="18" :class="{ spinning: loading }" /></button>
        <button class="primary" :disabled="remarkSaving" @click="openModal('add')"><Plus :size="17" />添加直播间</button>
      </div>
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <p v-if="statusError" class="error-banner" role="alert">录制状态获取失败：{{ statusError }}</p>
    <DiskStatus compact />
    <div class="table-wrap" :aria-busy="loading">
      <table>
        <thead><tr><th>平台</th><th>主播 / 房间号</th><th>备注</th><th>标题</th><th>监控</th><th>录制状态</th><th>录制健康</th><th>录制时长</th><th>最近开播</th><th class="actions-head">操作</th></tr></thead>
        <tbody>
          <tr v-for="room in rooms" :key="room.id">
            <td><span class="platform-badge" :class="room.platform.toLowerCase()">{{ platformName(room.platform) }}</span></td>
            <td><div class="owner-cell"><img v-if="safeUrl(room.avatar)" :src="safeUrl(room.avatar)" class="avatar" referrerpolicy="no-referrer" alt="" @error="($event.target.style.display = 'none')" /><div><strong>{{ room.owner || '-' }}</strong><a v-if="safeUrl(room.room_url)" :href="safeUrl(room.room_url)" target="_blank" rel="noopener noreferrer" class="secondary-text">{{ room.room_id }}</a><span v-else class="secondary-text">{{ room.room_id }}</span></div></div></td>
            <td class="remark-cell">
              <template v-if="remarkEditingId === room.id">
                <form class="remark-editor" @submit.prevent="saveRemark(room)">
                  <input :ref="setRemarkInput" v-model="remarkDraft" :aria-label="`备注 ${room.owner || room.room_id}`" maxlength="512" :disabled="remarkSaving" @keydown.esc.prevent="cancelRemark" />
                  <button type="submit" class="icon-button" title="保存备注" aria-label="保存备注" :disabled="remarkSaving"><Check :size="16" /></button>
                  <button type="button" class="icon-button" title="取消编辑备注" aria-label="取消编辑备注" :disabled="remarkSaving" @click="cancelRemark"><X :size="16" /></button>
                </form>
                <p v-if="remarkError" class="error-text" role="alert">{{ remarkError }}</p>
              </template>
              <div v-else class="remark-display"><span>{{ room.remark || '-' }}</span><button class="icon-button" title="编辑备注" :aria-label="`编辑备注 ${room.owner || room.room_id}`" :disabled="remarkSaving" @click="editRemark(room)"><Pencil :size="15" /></button></div>
            </td>
            <td class="title-cell">{{ room.title || '-' }}</td>
            <td><input type="checkbox" role="switch" :aria-label="`监控 ${room.owner || room.room_id}`" :checked="room.monitor_enabled" :disabled="rowBusy.includes(room.id)" @change="roomAction(room, 'monitor', $event)" /></td>
            <td class="recording-state-cell"><span class="recording-state" :title="statuses[room.id]?.message" :class="{ recording: !statusError && statuses[room.id]?.state === 'recording', reconnecting: !statusError && statuses[room.id]?.state === 'reconnecting', 'error-text': statuses[room.id]?.state === 'disk_blocked' }">{{ recordingLabel(room) }}</span></td>
            <td class="recording-health-cell" :title="statuses[room.id]?.health?.last_error || statuses[room.id]?.message">
              <span :class="{ 'error-text': statuses[room.id]?.state === 'health_failed' }">{{ healthLabel(room) }}</span>
              <small v-if="!statusError && statuses[room.id]?.health" class="secondary-text">{{ formatBytes(statuses[room.id].health.output_bytes) }} / 恢复 {{ statuses[room.id].health.restart_count || 0 }} 次</small>
            </td>
            <td class="recording-duration">{{ recordingDuration(room) }}</td>
            <td class="time-cell">{{ formatTime(room.last_live_time) }}</td>
            <td><div class="row-actions">
              <button class="icon-button" title="立即录制" :aria-label="`录制 ${room.owner || room.room_id}`" :disabled="rowBusy.includes(room.id) || startBusy.includes(room.id) || ['recording', 'reconnecting', 'checking', 'preparing', 'finishing', 'merging', 'registering', 'stopping'].includes(statuses[room.id]?.state)" @click="startRecording(room)"><Play :size="17" /></button>
              <button class="icon-button danger" title="停止录制" :aria-label="`停止录制 ${room.owner || room.room_id}`" :disabled="saving || rowBusy.includes(room.id)" @click="openModal('stop', room)"><Square :size="17" /></button>
              <button class="icon-button" title="检查直播状态" :aria-label="`检查 ${room.owner || room.room_id}`" :disabled="rowBusy.includes(room.id)" @click="roomAction(room, 'check')"><Radio :size="17" /></button>
              <RouterLink class="icon-button" :to="{ path: '/logs', query: { room_id: room.id } }" title="录制日志" :aria-label="`日志 ${room.owner || room.room_id}`"><History :size="17" /></RouterLink>
              <button class="icon-button" title="运行日志" :aria-label="`运行日志 ${room.owner || room.room_id}`" @click="openLogs(room, $event)"><FileText :size="17" /></button>
              <button class="icon-button" :class="{ customized: room.recording_settings_customized }" :title="room.recording_settings_customized ? '录制设置（独立配置）' : '录制设置（继承全局）'" :aria-label="`录制设置 ${room.owner || room.room_id}`" @click="openRoomSettings(room, $event)"><SlidersHorizontal :size="17" /></button>
              <button class="icon-button" title="编辑直播间" :aria-label="`编辑 ${room.owner || room.room_id}`" :disabled="remarkSaving" @click="openModal('edit', room)"><Pencil :size="17" /></button>
              <button class="icon-button danger" title="删除直播间" :aria-label="`删除 ${room.owner || room.room_id}`" :disabled="remarkSaving" @click="openModal('delete', room)"><Trash2 :size="17" /></button>
            </div></td>
          </tr>
          <tr v-if="!rooms.length"><td colspan="10" class="empty-state">{{ loading ? '加载中…' : error ? '直播间加载失败' : keyword ? '没有匹配的直播间' : '暂无直播间' }}</td></tr>
        </tbody>
      </table>
    </div>
    <p class="list-count">{{ rooms.length }} 个直播间</p>
    <RoomRecordingSettings v-if="settingsRoom" :key="settingsRoom.id" :room="settingsRoom" @close="closeRoomSettings" @saved="roomSettingsSaved" />
    <ModalDialog v-if="logRoom" class="runtime-dialog" :title="'运行日志 · ' + (logRoom.remark || logRoom.owner || logRoom.room_id)" @close="closeLogs"><div class="runtime-dialog-body"><RuntimeLogPanel :key="logRoom.id" :room-id="logRoom.id" compact /><footer class="modal-actions"><RouterLink :to="{ path: '/runtime-logs', query: { room_id: logRoom.id } }" class="diagnostic-link"><FileText :size="16" />查看全部</RouterLink></footer></div></ModalDialog>
    <ModalDialog v-if="modal" :title="modal === 'add' ? '添加直播间' : modal === 'edit' ? '编辑直播间' : modal === 'stop' ? '停止录制' : '删除直播间'" :busy="saving" @close="modal = null">
      <form v-if="modal === 'add' || modal === 'edit'" class="modal-body" @submit.prevent="saveRoom">
        <label v-if="modal === 'add'" class="field">直播间 URL<input v-model="draft.room_url" type="url" required autofocus placeholder="https://live.douyin.com/…" :disabled="saving" /></label>
        <template v-else>
          <label class="field">主播昵称<input v-model="draft.owner" maxlength="255" :disabled="saving" /></label>
          <label class="field">标题<input v-model="draft.title" maxlength="512" :disabled="saving" /></label>
        </template>
        <label class="field">备注<input v-model="draft.remark" maxlength="512" :disabled="saving" /></label>
        <label class="checkbox-label"><input v-model="draft.monitor_enabled" type="checkbox" :disabled="saving" />启用监控</label>
        <p v-if="formError" class="error-text" role="alert">{{ formError }}</p>
        <footer class="modal-actions"><button type="button" :disabled="saving" @click="modal = null">取消</button><button type="submit" class="primary" :disabled="saving">{{ saving ? '提交中…' : modal === 'add' ? '添加' : '保存' }}</button></footer>
      </form>
      <form v-else-if="modal === 'stop'" class="modal-body" @submit.prevent="stopRecording">
        <p>{{ selected.owner || selected.room_id }}</p>
        <label class="checkbox-label"><input v-model="disableMonitor" type="radio" :value="true" :disabled="saving" />停止并暂停监控</label>
        <label class="checkbox-label"><input v-model="disableMonitor" type="radio" :value="false" :disabled="saving" />停止本次，保留监控</label>
        <p v-if="formError" class="error-text" role="alert">{{ formError }}</p>
        <footer class="modal-actions"><button type="button" :disabled="saving" @click="modal = null">取消</button><button type="submit" class="danger-solid" :disabled="saving">{{ saving ? '停止中…' : '确认停止' }}</button></footer>
      </form>
      <div v-else class="modal-body">
        <p>确定删除「{{ selected.owner || selected.room_id }}」？</p>
        <p v-if="formError" class="error-text" role="alert">{{ formError }}</p>
        <footer class="modal-actions"><button :disabled="saving" @click="modal = null">取消</button><button class="danger-solid" :disabled="saving" @click="removeRoom">{{ saving ? '删除中…' : '确认删除' }}</button></footer>
      </div>
    </ModalDialog>
  </section>
</template>
