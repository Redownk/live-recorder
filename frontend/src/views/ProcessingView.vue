<script setup>
import { computed, inject, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ArrowDown, ArrowUp, Check, CircleStop, FileVideo, FolderOpen, Plus, RefreshCw, Trash2 } from '@lucide/vue';
import { api } from '../api.js';
import DirectoryPicker from '../components/DirectoryPicker.vue';
import ModalDialog from '../components/ModalDialog.vue';

const route = useRoute();
const notify = inject('notify');
const mode = computed(() => route.params.mode);
const files = ref([]);
const jobs = ref([]);
const encoders = ref([]);
const error = ref('');
const jobsError = ref('');
const capabilitiesError = ref('');
const submitting = ref(false);
const picker = ref('');
const removeConfirmation = ref(false);
const addButton = ref(null);
const outputButton = ref(null);
const browsePath = ref('');
const highFrequency = ref(false);
const options = reactive({ encoder: 'libx264', preset: 'default', container: 'mp4', save_original: true, output_directory: '', output_name: 'merged', existing: 'skip', remove_source: false, keep_metadata: true, merge_subtitles: false });
const states = { queued: '排队中', running: '处理中', cancelling: '正在取消', cancelled: '已取消', failed: '失败', completed: '已完成', skipped: '已跳过' };
const active = (job) => ['queued', 'running', 'cancelling'].includes(job.status);
const name = (path) => path.split(/[\\/]/).pop();
const visibleJobs = computed(() => jobs.value.filter((job) => job.mode === mode.value));
const canStart = computed(() => !submitting.value && files.value.length >= (mode.value === 'merge' ? 2 : 1) && (options.save_original || options.output_directory.trim()) && (mode.value === 'merge' || encoders.value.some((item) => item.value === options.encoder && item.available)));
let timer;
let disposed = false;
let cancelling = new Set();

async function loadCapabilities() {
  try {
    const data = await api.processingCapabilities();
    if (disposed) return;
    encoders.value = data.encoders;
    capabilitiesError.value = data.error;
    if (!encoders.value.some((item) => item.value === options.encoder && item.available)) {
      options.encoder = encoders.value.find((item) => item.available)?.value || 'libx264';
    }
  } catch (err) { if (!disposed) capabilitiesError.value = err.message; }
}
async function refreshJobs() {
  try {
    const data = await api.processingJobs();
    if (!disposed) { jobs.value = data; jobsError.value = ''; }
  } catch (err) { if (!disposed) jobsError.value = err.message; }
  finally { if (!disposed) timer = setTimeout(refreshJobs, highFrequency.value ? 500 : 1500); }
}
function move(index, direction) {
  const items = [...files.value];
  [items[index], items[index + direction]] = [items[index + direction], items[index]];
  files.value = items;
}
function openPicker(kind) { picker.value = kind; }
async function closePicker() {
  const target = picker.value === 'files' ? addButton.value : outputButton.value;
  picker.value = '';
  await nextTick();
  target?.focus();
}
function choose(value) {
  if (picker.value === 'files') files.value = [...new Set([...files.value, ...value])];
  else options.output_directory = value;
  closePicker();
}
async function submit(confirmed = false) {
  if (!canStart.value) return;
  if (mode.value === 'transcode' && options.remove_source && !confirmed) { removeConfirmation.value = true; return; }
  removeConfirmation.value = false;
  submitting.value = true;
  error.value = '';
  try {
    const job = await api.createProcessingJob({ ...options, mode: mode.value, files: [...files.value], remove_source: mode.value === 'transcode' && options.remove_source, merge_subtitles: mode.value === 'merge' && options.merge_subtitles });
    if (!disposed) { jobs.value = [job, ...jobs.value.filter((item) => item.id !== job.id)]; notify('已加入视频处理队列'); }
  } catch (err) { if (!disposed) error.value = err.message; }
  finally { if (!disposed) submitting.value = false; }
}
async function cancel(job) {
  if (cancelling.has(job.id)) return;
  cancelling.add(job.id);
  job.status = 'cancelling';
  try {
    const result = await api.cancelProcessingJob(job.id);
    if (!disposed) jobs.value = jobs.value.map((item) => item.id === job.id ? result : item);
  } catch (err) { if (!disposed) error.value = err.message; }
  finally { cancelling.delete(job.id); }
}
watch(mode, () => { error.value = ''; removeConfirmation.value = false; picker.value = ''; });
onMounted(() => {
  loadCapabilities();
  refreshJobs();
  api.settings().then((data) => { if (!disposed) browsePath.value = data.resolved_save_path; }).catch(() => {});
});
onUnmounted(() => { disposed = true; clearTimeout(timer); });
</script>

<template>
  <section class="processing-page">
    <div class="processing-tabs" aria-label="视频处理类型">
      <RouterLink to="/processing/transcode">转码</RouterLink>
      <RouterLink to="/processing/merge">合并</RouterLink>
    </div>
    <p v-if="error || jobsError" class="error-banner" role="alert">{{ error || jobsError }}</p>
    <p v-if="capabilitiesError && mode === 'transcode'" class="error-banner" role="alert">{{ capabilitiesError }} <button type="button" class="icon-button" title="重新检测编码器" aria-label="重新检测编码器" @click="loadCapabilities"><RefreshCw :size="16" /></button></p>
    <div class="processing-toolbar">
      <button ref="addButton" type="button" @click="openPicker('files')"><Plus :size="17" />添加</button>
      <button type="button" class="primary" :disabled="!canStart" @click="submit()"><Check :size="17" />{{ submitting ? '正在提交' : mode === 'merge' ? '立即合并' : '立即转换' }}</button>
      <template v-if="mode === 'transcode'">
        <label class="field">编码器<select v-model="options.encoder" aria-label="编码器"><option v-for="encoder in encoders" :key="encoder.value" :value="encoder.value" :disabled="!encoder.available">{{ encoder.label }}{{ encoder.available ? '' : ' · 不支持' }}</option></select></label>
        <label class="field">转码规则<select v-model="options.preset" aria-label="转码规则" :disabled="options.encoder === 'copy'"><option value="default">默认配置</option><option value="quality">高质量</option><option value="fast">快速压缩</option></select></label>
      </template>
      <label class="field">输出格式<select v-model="options.container" aria-label="输出格式"><option value="mp4">MP4</option><option value="mkv">MKV</option><option value="ts">TS</option></select></label>
      <label v-if="mode === 'transcode'" class="checkbox-label"><input v-model="highFrequency" type="checkbox" />高频进度更新</label>
      <label v-else class="checkbox-label"><input v-model="options.merge_subtitles" type="checkbox" />合并弹幕 / 字幕</label>
    </div>
    <button v-if="!files.length" class="processing-empty" type="button" @click="openPicker('files')"><FileVideo :size="44" /><span>选择视频文件</span></button>
    <div v-else class="table-wrap processing-files"><table><thead><tr><th>#</th><th>视频文件</th><th>操作</th></tr></thead><tbody><tr v-for="(file, index) in files" :key="file"><td>{{ index + 1 }}</td><td class="filename-cell"><strong>{{ name(file) }}</strong><span class="secondary-text">{{ file }}</span></td><td><div class="row-actions"><template v-if="mode === 'merge'"><button class="icon-button" type="button" title="上移" :aria-label="`上移 ${name(file)}`" :disabled="index === 0" @click="move(index, -1)"><ArrowUp :size="16" /></button><button class="icon-button" type="button" title="下移" :aria-label="`下移 ${name(file)}`" :disabled="index === files.length - 1" @click="move(index, 1)"><ArrowDown :size="16" /></button></template><button class="icon-button danger" type="button" title="移除文件" :aria-label="`移除 ${name(file)}`" @click="files.splice(index, 1)"><Trash2 :size="16" /></button></div></td></tr></tbody></table></div>
    <fieldset class="processing-options" :disabled="submitting">
      <div class="processing-output">
        <label class="checkbox-label"><input v-model="options.save_original" type="checkbox" />保存到原始文件夹</label>
        <div v-if="!options.save_original" class="save-path-input"><input v-model="options.output_directory" aria-label="输出目录" maxlength="1024" /><button ref="outputButton" type="button" class="icon-button" title="选择输出目录" aria-label="选择输出目录" @click="openPicker('directory')"><FolderOpen :size="19" /></button></div>
        <label v-if="mode === 'merge'" class="field">输出文件名<input v-model="options.output_name" aria-label="输出文件名" maxlength="180" /></label>
      </div>
      <div class="processing-flags">
        <label class="checkbox-label"><input v-model="options.existing" type="radio" value="skip" name="existing" />跳过存在文件</label>
        <label class="checkbox-label"><input v-model="options.existing" type="radio" value="overwrite" name="existing" />覆盖文件</label>
        <label class="checkbox-label"><input v-model="options.keep_metadata" type="checkbox" />保留元数据</label>
        <label v-if="mode === 'transcode'" class="checkbox-label"><input v-model="options.remove_source" type="checkbox" />完成后移除源文件</label>
      </div>
    </fieldset>
    <section class="processing-history" aria-label="处理任务">
      <h2>处理任务</h2>
      <p v-if="!visibleJobs.length" class="muted">暂无任务</p>
      <article v-for="job in visibleJobs" :key="job.id" class="processing-job">
        <div class="processing-job-heading"><strong>{{ job.current_file || name(job.files[0]) }}</strong><span class="processing-job-state" :class="job.status">{{ states[job.status] }}</span><button v-if="active(job)" class="icon-button" type="button" title="取消任务" aria-label="取消任务" :disabled="job.status === 'cancelling'" @click="cancel(job)"><CircleStop :size="17" /></button></div>
        <div class="processing-progress"><progress max="100" :value="job.progress" aria-label="处理进度"></progress><span>{{ job.progress }}%</span></div>
        <p v-if="job.error" class="error-text">{{ job.error }}</p><p v-if="job.warning" class="muted">{{ job.warning }}</p>
        <p v-for="output in job.outputs" :key="output" class="secondary-text processing-result">{{ output }}</p>
      </article>
    </section>
    <DirectoryPicker v-if="picker" :files="picker === 'files'" :initial-path="picker === 'files' ? browsePath : options.output_directory || browsePath" @close="closePicker" @select="choose" />
    <ModalDialog v-if="removeConfirmation" title="确认移除源文件" @close="removeConfirmation = false"><div class="modal-body"><p>转码成功后将删除所选源视频。失败、取消或跳过的文件会保留。</p><footer class="modal-actions"><button type="button" @click="removeConfirmation = false">取消</button><button type="button" class="danger-solid" @click="submit(true)">确认转换并移除</button></footer></div></ModalDialog>
  </section>
</template>
