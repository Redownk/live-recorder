<script setup>
import { onMounted, ref, useId } from 'vue';
import { X } from '@lucide/vue';

defineProps({ title: { type: String, required: true }, busy: Boolean });
const emit = defineEmits(['close']);
const dialog = ref(null);
const titleId = useId();
onMounted(() => dialog.value.showModal());
</script>

<template>
  <dialog ref="dialog" class="modal" :aria-labelledby="titleId" @cancel.prevent="!busy && emit('close')">
    <header class="modal-header">
      <h2 :id="titleId">{{ title }}</h2>
      <button class="icon-button" title="关闭" aria-label="关闭" :disabled="busy" @click="emit('close')"><X :size="18" /></button>
    </header>
    <slot />
  </dialog>
</template>
