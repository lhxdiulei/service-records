<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import '../pagination-controls.css'
const props = defineProps({ page: { type: Number, default: 1 }, total: { type: Number, default: 0 }, pageSize: { type: Number, default: 10 }, disabled: Boolean })
const emit = defineEmits(['change'])
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const target = ref(props.page)
const jumpOpen = ref(false)
const jumpInput = ref(null)
const jumpToggle = ref(null)
const validTarget = computed(() => Number.isInteger(Number(target.value)) && Number(target.value) >= 1 && Number(target.value) <= pages.value)
watch(() => [props.page, pages.value], () => {
  target.value = props.page
  if (pages.value <= 1) jumpOpen.value = false
})
function closeJump() {
  jumpOpen.value = false
  jumpToggle.value?.focus?.()
}
async function toggleJump() {
  if (props.disabled) return
  if (jumpOpen.value) return closeJump()
  target.value = props.page
  jumpOpen.value = true
  await nextTick()
  jumpInput.value?.focus?.()
  jumpInput.value?.select?.()
}
function go(value) {
  const n = Number(value)
  if (!props.disabled && Number.isInteger(n) && n >= 1 && n <= pages.value && n !== props.page) {
    if (jumpOpen.value) closeJump()
    emit('change', n)
  }
}
</script>

<template>
  <nav class="pagination pagination-compact" aria-label="分页">
    <span class="muted">共 {{total}} 条 · 每页 {{pageSize}} 条</span>
    <div v-if="pages > 1" class="pagination-actions">
      <button type="button" class="small" :disabled="disabled || page <= 1" @click="go(page - 1)">上一页</button>
      <span aria-live="polite">第 {{page}} / {{pages}} 页</span>
      <button type="button" class="small" :disabled="disabled || page >= pages" @click="go(page + 1)">下一页</button>
      <button ref="jumpToggle" type="button" class="small pagination-jump-toggle" :disabled="disabled" :aria-expanded="jumpOpen" @click="toggleJump">{{jumpOpen ? '收起跳页' : '跳页'}}</button>
    </div>
    <form v-if="pages > 1 && jumpOpen" class="pagination-jump pagination-jump-panel" aria-label="跳转至指定页面" @submit.prevent="go(target)" @keydown.esc.prevent.stop="closeJump">
      <button type="button" class="small" :disabled="disabled || page <= 1" @click="go(1)">首页</button>
      <button type="button" class="small" :disabled="disabled || page >= pages" @click="go(pages)">末页</button>
      <label>跳至<input ref="jumpInput" v-model.number="target" type="number" min="1" :max="pages" step="1" :disabled="disabled" :aria-invalid="!validTarget" aria-label="跳转页码">页</label>
      <button type="submit" class="small" :disabled="disabled || !validTarget || Number(target) === page">确定</button>
      <span v-if="!validTarget" class="pagination-jump-hint" role="status">请输入 1 至 {{pages}} 的整数页码</span>
    </form>
  </nav>
</template>
