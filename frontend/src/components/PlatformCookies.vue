<script setup>
import { inject, onUnmounted, reactive, ref } from 'vue';
import { Eye, EyeOff, RefreshCw } from '@lucide/vue';
import { api } from '../api.js';

const notify = inject('notify');
const platforms = reactive([
  { platform: 'douyin', name: '抖音' }, { platform: 'bilibili', name: '哔哩哔哩' }, { platform: 'douyu', name: '斗鱼' },
].map((platform) => ({ ...platform, cookie: '', configured: false, visible: false, busy: false, error: '' })));
const loading = ref(true);
const loadError = ref('');
let disposed = false;

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    const data = await api.platformCookies();
    if (!Array.isArray(data.platforms) || platforms.some((row) => typeof data.platforms.find((item) => item.platform === row.platform)?.configured !== 'boolean')) {
      throw new Error('平台 Cookie 状态响应不正确');
    }
    if (!disposed) for (const row of platforms) row.configured = data.platforms.find((item) => item.platform === row.platform).configured;
  } catch (err) { if (!disposed) loadError.value = err.message; }
  finally { if (!disposed) loading.value = false; }
}

async function save(row, clear = false) {
  if (row.busy || (!clear && !row.cookie.trim())) return;
  row.busy = true;
  row.error = '';
  try {
    const state = clear ? await api.clearPlatformCookie(row.platform) : await api.savePlatformCookie(row.platform, row.cookie);
    if (!disposed) {
      row.configured = state.configured;
      row.cookie = '';
      row.visible = false;
      notify(`${row.name} Cookie ${clear ? '已清除' : '已保存'}`);
    }
  } catch (err) { if (!disposed) row.error = err.message; }
  finally { if (!disposed) row.busy = false; }
}

onUnmounted(() => { disposed = true; for (const row of platforms) row.cookie = ''; });
load();
</script>

<template>
  <section class="settings-section platform-cookies" aria-label="平台 Cookie">
    <h2>平台 Cookie</h2>
    <p class="muted">保存后用于后续直播检查和播放流请求。已保存的 Cookie 不回显，留空不会修改。</p>
    <p v-if="loading" class="muted">正在加载平台配置…</p>
    <div v-else-if="loadError" class="error-banner" role="alert">{{ loadError }}<button type="button" class="icon-button" aria-label="重试加载平台 Cookie" @click="load"><RefreshCw :size="17" /></button></div>
    <template v-else>
      <div v-for="row in platforms" :key="row.platform" class="platform-cookie-row" role="group" :aria-label="`${row.name} Cookie 配置`">
        <div class="platform-cookie-heading"><label :for="`cookie-${row.platform}`">{{ row.name }} Cookie</label><span class="muted">{{ row.configured ? '已配置' : '未配置' }}</span></div>
        <div class="platform-cookie-input">
          <input :id="`cookie-${row.platform}`" v-model="row.cookie" :type="row.visible ? 'text' : 'password'" :placeholder="row.configured ? '已配置，输入新的 Cookie 以替换' : '粘贴 Cookie 请求头内容'" :disabled="row.busy" maxlength="16384" autocomplete="off" spellcheck="false" @keydown.enter.prevent="save(row)" />
          <button type="button" class="icon-button" :aria-label="`${row.visible ? '隐藏' : '显示'}${row.name} Cookie`" :aria-pressed="row.visible" :disabled="row.busy || !row.cookie" @click="row.visible = !row.visible"><EyeOff v-if="row.visible" :size="17" /><Eye v-else :size="17" /></button>
        </div>
        <p v-if="row.error" class="error-text" role="alert">{{ row.error }}</p>
        <div class="platform-cookie-actions"><button type="button" :aria-label="`保存${row.name} Cookie`" :disabled="row.busy || !row.cookie.trim()" @click="save(row)">{{ row.busy ? '处理中…' : '保存' }}</button><button type="button" :aria-label="`清除${row.name} Cookie`" :disabled="row.busy || !row.configured" @click="save(row, true)">清除</button></div>
      </div>
    </template>
  </section>
</template>
