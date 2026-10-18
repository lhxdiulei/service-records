<script setup>
import { nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { MoreHorizontal } from 'lucide-vue-next'
import '../more-actions.css'

const props = defineProps({ disabled: Boolean, label: { type: String, default: '更多操作' } })
const container = ref(null), trigger = ref(null), opened = ref(false)
const menu = ref(null), placement = ref({})
const contentId = useId()

function positionMenu() {
  if (!opened.value || !trigger.value || !menu.value) return
  if (window.innerWidth > 780) { placement.value = {}; return }
  const viewport = window.visualViewport
  const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0
  const width = viewport?.width || window.innerWidth, height = viewport?.height || window.innerHeight
  const rect = trigger.value.getBoundingClientRect()
  const menuWidth = Math.min(240, width - 16)
  const below = top + height - rect.bottom - 12, above = rect.top - top - 12
  const upward = below < Math.min(menu.value.scrollHeight, 220) && above > below
  const menuHeight = Math.min(height - 16, Math.max(80, upward ? above : below), menu.value.scrollHeight)
  const menuTop = upward ? rect.top - menuHeight - 5 : rect.bottom + 5
  placement.value = {
    left: `${Math.max(left + 8, Math.min(rect.right - menuWidth, left + width - menuWidth - 8))}px`,
    top: `${Math.max(top + 8, Math.min(menuTop, top + height - menuHeight - 8))}px`,
    width: `${menuWidth}px`, maxHeight: `${menuHeight}px`,
  }
}
function onScroll(event) {
  if (!menu.value?.contains(event.target)) positionMenu()
}
function listenPosition(method) {
  window[method]('resize', positionMenu)
  window[method]('scroll', onScroll, true)
  window.visualViewport?.[method]('resize', positionMenu)
  window.visualViewport?.[method]('scroll', positionMenu)
}
function close() {
  if (container.value) container.value.open = false
  opened.value = false
}
function guardDisabled(event) {
  if (!props.disabled) return
  event.preventDefault()
  event.stopPropagation()
  close()
}
function onToggle(event) {
  if (props.disabled) close()
  else opened.value = event.target.open
}
function onClick(event) {
  // Row click handlers must never run when a menu action is used.
  event.stopPropagation()
  const button = event.target.closest?.('button')
  if (button && container.value?.contains(button) && !button.disabled) close()
}
async function onKeydown(event) {
  if (event.key !== 'Escape' || !container.value?.open) return
  event.preventDefault()
  event.stopPropagation()
  close()
  await nextTick()
  if (!props.disabled) trigger.value?.focus()
}
function onOutsidePointer(event) {
  if (container.value?.open && !container.value.contains(event.target)) close()
}
watch(() => props.disabled, disabled => { if (disabled) close() })
watch(opened, async value => {
  listenPosition(value ? 'addEventListener' : 'removeEventListener')
  if (value) { await nextTick(); positionMenu() }
  else placement.value = {}
})
onMounted(() => document.addEventListener('pointerdown', onOutsidePointer, true))
onUnmounted(() => {
  document.removeEventListener('pointerdown', onOutsidePointer, true)
  listenPosition('removeEventListener')
})
</script>

<template>
  <details ref="container" class="more-actions" :class="{ 'is-disabled': disabled }"
    @toggle="onToggle" @click.capture="guardDisabled" @click="onClick" @keydown="onKeydown">
    <summary ref="trigger" :aria-label="label" :aria-disabled="disabled" :aria-expanded="opened" :aria-controls="contentId"
      :tabindex="disabled ? -1 : 0" @keydown="guardDisabled">
      <MoreHorizontal :size="15" aria-hidden="true"/><span>{{ label }}</span>
    </summary>
    <div :id="contentId" ref="menu" class="more-actions__items" :style="placement" :inert="disabled">
      <slot/>
    </div>
  </details>
</template>
