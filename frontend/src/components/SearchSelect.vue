<script setup>
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { Check, ChevronDown, Search, X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '输入关键词搜索并选择' },
  ariaLabel: { type: String, required: true },
  inputId: String,
  describedBy: String,
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue', 'change'])
const uid = useId(), root = ref(null), input = ref(null), panel = ref(null)
const open = ref(false), query = ref(''), active = ref(-1), composing = ref(false), placement = ref({})
const id = computed(() => props.inputId || `search-select-${uid}`)
const selected = computed(() => props.options.find(o => String(o.value) === String(props.modelValue ?? '')))
const filtered = computed(() => {
  const terms = query.value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean)
  return props.options.filter(o => {
    const text = `${o.label} ${o.description || ''} ${o.searchText || ''}`.toLocaleLowerCase()
    return terms.every(term => text.includes(term))
  })
})
const optionId = index => `${id.value}-option-${index}`

function position() {
  if (!root.value || !panel.value) return
  const rect = root.value.getBoundingClientRect()
  // The visual viewport shrinks when a phone keyboard is open.
  const viewport = window.visualViewport
  const viewportLeft = viewport?.offsetLeft || 0, viewportTop = viewport?.offsetTop || 0
  const viewportWidth = viewport?.width || window.innerWidth
  const viewportHeight = viewport?.height || window.innerHeight
  const viewportBottom = viewportTop + viewportHeight
  const below = viewportBottom - rect.bottom - 12, above = rect.top - viewportTop - 12
  const upward = below < 220 && above > below
  const height = Math.max(0, Math.min(viewportHeight - 16, Math.max(80, Math.min(340, upward ? above : below))))
  const width = Math.max(0, Math.min(rect.width, viewportWidth - 16))
  // Anchor an upward panel by its bottom so short result lists stay next to the field.
  const edge = upward
    ? Math.max(viewportTop + height + 8, Math.min(rect.top - 5, viewportBottom - 8))
    : Math.max(viewportTop + 8, Math.min(rect.bottom + 5, viewportBottom - height - 8))
  placement.value = {
    left: `${Math.max(viewportLeft + 8, Math.min(rect.left, viewportLeft + viewportWidth - width - 8))}px`,
    width: `${width}px`,
    maxHeight: `${height}px`,
    ...(upward ? { bottom: `${window.innerHeight - edge}px` } : { top: `${edge}px` }),
  }
}
function outside(event) {
  if (!root.value?.contains(event.target) && !panel.value?.contains(event.target)) close()
}
function scrolling(event) {
  if (!panel.value?.contains(event.target)) position()
}
function close() { open.value = false; query.value = '' }
async function show() {
  if (props.disabled || open.value) return
  query.value = ''; open.value = true
  active.value = Math.max(0, filtered.value.findIndex(o => String(o.value) === String(props.modelValue ?? '')))
  await nextTick(); position(); reveal()
}
function update(value) {
  const changed = value !== props.modelValue
  emit('update:modelValue', value)
  if (changed) emit('change', value)
}
function choose(option) {
  if (props.disabled) return
  update(option.value); close(); input.value?.focus()
}
function search(event) {
  if (!open.value) {
    open.value = true
    nextTick(() => position())
  }
  query.value = event.target.value
  // A typed query is not a selected record. Invalidate the previous target immediately.
  if (props.modelValue !== '' && props.modelValue != null) emit('update:modelValue', '')
  active.value = filtered.value.length ? 0 : -1
}
function clear() {
  update(''); query.value = ''; input.value?.focus(); show()
  active.value = filtered.value.length ? 0 : -1
}
async function toggle() {
  if (open.value) close()
  else { input.value?.focus(); await show() }
}
function reveal() {
  nextTick(() => document.getElementById(optionId(active.value))?.scrollIntoView({ block: 'nearest' }))
}
function keydown(event) {
  if (event.isComposing || composing.value) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) { show(); return }
    const count = filtered.value.length
    active.value = count ? (active.value + (event.key === 'ArrowDown' ? 1 : -1) + count) % count : -1
    reveal()
  } else if (event.key === 'Enter' && open.value) {
    event.preventDefault()
    const option = filtered.value[active.value]
    if (option) choose(option)
  } else if (event.key === 'Escape' && open.value) {
    event.preventDefault(); event.stopPropagation(); close()
  } else if (event.key === 'Tab') close()
}
watch(open, value => {
  const method = value ? 'addEventListener' : 'removeEventListener'
  document[method]('pointerdown', outside)
  window[method]('resize', position)
  window[method]('scroll', scrolling, true)
  window.visualViewport?.[method]('resize', position)
  window.visualViewport?.[method]('scroll', position)
})
watch(() => props.disabled, disabled => { if (disabled) close() })
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', position)
  window.removeEventListener('scroll', scrolling, true)
  window.visualViewport?.removeEventListener('resize', position)
  window.visualViewport?.removeEventListener('scroll', position)
})
</script>

<template>
  <div ref="root" class="search-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <Search class="search-select__search" :size="16" aria-hidden="true"/>
    <input :id="id" ref="input" class="search-select__input" type="text" role="combobox"
      :aria-label="ariaLabel" :aria-describedby="describedBy" aria-autocomplete="list"
      :aria-expanded="open" :aria-controls="`${id}-list`" :aria-activedescendant="open && active >= 0 && filtered[active] ? optionId(active) : undefined"
      :value="open ? query : (selected?.label || '')" :placeholder="open && selected ? `搜索：${selected.label}` : placeholder"
      :disabled="disabled" autocomplete="off" @focus="show" @click="show" @input="search" @keydown="keydown"
      @blur="close" @compositionstart="composing=true" @compositionend="composing=false">
    <button v-if="modelValue !== '' && modelValue != null || query" type="button" class="search-select__icon" :disabled="disabled"
      :aria-label="`清空${ariaLabel}`" @pointerdown.prevent @click="clear"><X :size="15"/></button>
    <button type="button" class="search-select__icon" :disabled="disabled" tabindex="-1"
      :aria-label="`${open ? '收起' : '展开'}${ariaLabel}`" @pointerdown.prevent @click="toggle"><ChevronDown :size="16"/></button>
    <Teleport to="body">
      <div v-if="open" ref="panel" class="search-select__panel" :style="placement" @pointerdown.prevent>
        <div :id="`${id}-list`" class="search-select__list" role="listbox" :aria-label="ariaLabel">
          <div v-for="(option, index) in filtered" :id="optionId(index)" :key="option.value" role="option"
            class="search-select__option" :class="{ 'is-active': active === index }"
            :aria-selected="String(option.value) === String(modelValue ?? '')" @pointermove="active=index" @click="choose(option)">
            <div><span>{{option.label}}</span><small v-if="option.description">{{option.description}}</small></div>
            <Check v-if="String(option.value) === String(modelValue ?? '')" :size="16" aria-hidden="true"/>
          </div>
          <p v-if="!filtered.length" class="search-select__empty" role="status">没有匹配的记录，换个关键词试试</p>
        </div>
        <div class="search-select__hint" role="status">{{filtered.length}} 条匹配 · 输入关键词筛选，再选择记录</div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.search-select { position:relative; display:flex; align-items:center; gap:0; width:100%; min-width:0; min-height:42px; border:1px solid var(--line, #dce5df); border-radius:6px; background:#fff; color:var(--text, #25483f); font-size:14px; font-weight:400; }
.search-select:focus-within { border-color:#4d9987; box-shadow:0 0 0 3px #2d8a7014; }
.search-select__search { flex:0 0 16px; margin-left:12px; color:#81988d; }
.search-select .search-select__input { width:100%; min-width:0; flex:1 1 0%; border:0; background:transparent; box-shadow:none; outline:none; padding:10px 9px; margin:0; font:inherit; color:inherit; text-overflow:ellipsis; }
.search-select__input::placeholder { color:#8b9b94; }
.search-select .search-select__icon { flex:0 0 30px; width:30px; min-width:30px; height:32px; padding:0; margin:0 3px 0 0; border:0; background:transparent; color:#799085; border-radius:4px; box-shadow:none; }
.search-select__icon:hover { background:#edf5f0; color:#226353; }
.search-select__icon:focus-visible { outline:2px solid #68a894; outline-offset:-2px; }
.search-select.is-disabled { background:#f4f6f4; opacity:.6; }
.search-select__panel { position:fixed; z-index:100; display:flex; flex-direction:column; overflow:hidden; border:1px solid #d5e4db; border-radius:8px; box-shadow:0 8px 28px #1e483624; background:#fff; font-family:inherit; font-size:13px; font-weight:400; line-height:1.6; color:var(--text, #25483f); }
.search-select__list { overflow:auto; overscroll-behavior:contain; min-height:0; padding:5px; }
.search-select__option { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:9px 11px; margin:1px 0; border-radius:5px; cursor:pointer; font-size:13px; line-height:1.6; }
.search-select__option > div { min-width:0; }
.search-select__option span { display:block; overflow-wrap:anywhere; }
.search-select__option small { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; font-size:11px; color:#809187; margin-top:3px; white-space:pre-line; overflow-wrap:anywhere; }
.search-select__option > svg { flex-shrink:0; color:#287761; }
.search-select__option.is-active { background:#edf5f0; }
.search-select__hint { flex-shrink:0; padding:8px 14px; border-top:1px solid #edf1ee; font-size:11px; color:#809187; background:#fbfcfb; }
.search-select__empty { padding:20px 12px; margin:0; font-size:13px; color:#819187; text-align:center; }
@media (max-width:780px) {
  .search-select { min-height:46px; font-size:16px; box-sizing:border-box; }
  .search-select .search-select__input { min-height:44px; padding:10px 8px; font-size:16px; }
  .search-select .search-select__icon { flex-basis:44px; width:44px; min-width:44px; height:44px; margin-right:0; }
  .search-select__search { margin-left:10px; }
  .search-select__panel { box-sizing:border-box; font-size:14px; }
  .search-select__option { min-height:44px; padding:11px 10px; font-size:14px; }
  .search-select__option small { font-size:12px; }
  .search-select__hint { padding:9px 12px; font-size:12px; overflow-wrap:anywhere; }
}
</style>
