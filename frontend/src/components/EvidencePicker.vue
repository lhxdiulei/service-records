<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Search, Quote } from 'lucide-vue-next'
import SearchSelect from './SearchSelect.vue'
import Pagination from './Pagination.vue'
import { excerptOccurrences, selectionEvidence } from '../editor-assist.js'
import '../evidence-picker.css'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  fields: { type: Array, default: () => [] },
  fieldKey: { type: String, default: '' },
  busy: Boolean,
  focusRequest: { type: Object, default: null },
  selectionRequest: { type: Object, default: null },
})
const emit = defineEmits(['update:fieldKey', 'add'])
const root = ref(null), targetHeading = ref(null), messageList = ref(null), search = ref(''), page = ref(1)
const selection = ref(null), notice = ref(''), highlight = ref(null)
const manualMessage = ref(''), manualExcerpt = ref(''), manualOccurrence = ref('')
const sourceNodes = new Map()
const pageSize = 10
let focusVersion = 0
const target = computed(() => props.fields.find(field => field.value === props.fieldKey))
const filtered = computed(() => {
  const terms = search.value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean)
  return props.messages.filter(message => {
    const text = `${message.sender_name_raw || ''} ${message.raw_text || ''} ${message.source_filename || ''}`.toLocaleLowerCase()
    return terms.every(term => text.includes(term))
  })
})
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visible = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const manualOptions = computed(() => props.messages.filter(message => !message.is_deleted).map(message => ({
  value: message.id,
  label: `${message.sender_name_raw || '未知成员'} · ${formatDate(message.sent_at)}`,
  description: (message.raw_text || '').replace(/\s+/g, ' ').slice(0, 120),
  searchText: `${message.raw_text || ''} ${message.source_filename || ''}`,
})))
const manualSource = computed(() => props.messages.find(message => String(message.id) === String(manualMessage.value) && !message.is_deleted))
const manualMatches = computed(() => manualSource.value ? excerptOccurrences(manualSource.value.raw_text || '', manualExcerpt.value) : [])
const manualMatch = computed(() => manualMatches.value.length === 1 ? manualMatches.value[0] : manualMatches.value.find(match => String(match.occurrence) === String(manualOccurrence.value)))
const manualReady = computed(() => !props.busy && !!target.value && !!manualMatch.value)

function formatDate(value) {
  if (!value) return '时间待确认'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
function setSourceNode(id, element) {
  if (element) sourceNodes.set(String(id), element)
  else sourceNodes.delete(String(id))
}
function rawNode(node) {
  const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement
  const source = element?.closest('[data-evidence-raw]')
  return source && root.value?.contains(source) ? source : null
}
function captureSelection() {
  if (props.busy) { selection.value = null; return }
  const selected = window.getSelection()
  if (!selected || selected.rangeCount !== 1 || selected.isCollapsed) { selection.value = null; return }
  const range = selected.getRangeAt(0)
  const pre = rawNode(range.startContainer)
  if (!pre || rawNode(range.endContainer) !== pre) { selection.value = null; return }
  const message = props.messages.find(item => String(item.id) === pre.dataset.evidenceRaw)
  if (!message || message.is_deleted || typeof message.raw_text !== 'string' || pre.textContent !== message.raw_text) {
    selection.value = null
    return
  }
  try {
    const beforeStart = document.createRange(), beforeEnd = document.createRange()
    beforeStart.selectNodeContents(pre); beforeStart.setEnd(range.startContainer, range.startOffset)
    beforeEnd.selectNodeContents(pre); beforeEnd.setEnd(range.endContainer, range.endOffset)
    const start = beforeStart.toString().length, end = beforeEnd.toString().length
    const evidence = selectionEvidence(message.raw_text, start, end)
    // DOM selection and persisted raw text must agree, including whitespace and CRLF.
    if (!evidence || evidence.exact_excerpt !== range.toString()) { selection.value = null; return }
    selection.value = { ...evidence, message_id: message.id, raw_text: message.raw_text }
    notice.value = ''
  } catch {
    selection.value = null
  }
}
function extendKeyboardSelection(event) {
  if (props.busy || !event.shiftKey || event.altKey) return
  const directions = { ArrowLeft: 'backward', ArrowRight: 'forward', ArrowUp: 'backward', ArrowDown: 'forward', Home: 'backward', End: 'forward' }
  const direction = directions[event.key], selected = window.getSelection()
  if (!direction || !selected || typeof selected.modify !== 'function') return
  const pre = event.currentTarget
  if (rawNode(selected.anchorNode) !== pre || rawNode(selected.focusNode) !== pre) {
    const range = document.createRange()
    range.selectNodeContents(pre); range.collapse(direction === 'forward')
    selected.removeAllRanges(); selected.addRange(range)
  }
  const granularity = event.key === 'Home' || event.key === 'End' ? 'lineboundary'
    : event.key === 'ArrowUp' || event.key === 'ArrowDown' ? 'line'
      : event.ctrlKey || event.metaKey ? 'word' : 'character'
  // A focusable pre is read-only, so browsers without caret browsing do not
  // extend it with Shift+Arrow themselves. Keep native text selection and
  // supply that keyboard operation without making the original editable.
  event.preventDefault()
  selected.modify('extend', direction, granularity)
  captureSelection()
}
function sendEvidence(message, evidence) {
  if (props.busy || !target.value || !message || message.is_deleted || !evidence?.exact_excerpt) return
  const match = excerptOccurrences(message.raw_text || '', evidence.exact_excerpt).find(item => item.occurrence === evidence.occurrence)
  if (!match) return
  emit('add', { message_id: message.id, exact_excerpt: evidence.exact_excerpt, occurrence: match.occurrence, field_key: props.fieldKey })
}
function addSelection(message) {
  const chosen = selection.value
  if (!chosen || chosen.message_id !== message.id || chosen.raw_text !== message.raw_text) return
  sendEvidence(message, chosen)
}
function addWhole(message) {
  const raw = message.raw_text || ''
  sendEvidence(message, selectionEvidence(raw, 0, raw.length))
}
function addManual() {
  if (!manualReady.value) return
  sendEvidence(manualSource.value, { exact_excerpt: manualExcerpt.value, occurrence: manualMatch.value.occurrence })
}
function matchLabel(match) {
  const points = Array.from(manualSource.value?.raw_text || '')
  const before = points.slice(Math.max(0, match.start_cp - 16), match.start_cp).join('').replace(/\s+/g, ' ')
  const after = points.slice(match.end_cp, match.end_cp + 16).join('').replace(/\s+/g, ' ')
  return `第 ${match.occurrence} 处 · ${before}【${manualExcerpt.value.replace(/\s+/g, ' ').slice(0, 28)}】${after}`
}
function messageParts(message) {
  const raw = message.raw_text || ''
  if (String(highlight.value?.message_id) !== String(message.id)) return [{ text: raw, selected: false }]
  const points = Array.from(raw), { start_cp: start, end_cp: end } = highlight.value
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > points.length) return [{ text: raw, selected: false }]
  return [
    { text: points.slice(0, start).join(''), selected: false },
    { text: points.slice(start, end).join(''), selected: true },
    { text: points.slice(end).join(''), selected: false },
  ]
}
async function focusSource(request) {
  if (!request?.message_id) return
  const version = ++focusVersion
  const index = props.messages.findIndex(message => String(message.id) === String(request.message_id))
  if (index < 0) { notice.value = '当前记录中未找到这条来源消息。'; return }
  search.value = ''
  selection.value = null
  highlight.value = { ...request }
  await nextTick()
  if (version !== focusVersion) return
  page.value = Math.floor(index / pageSize) + 1
  await nextTick()
  if (version !== focusVersion) return
  const node = sourceNodes.get(String(request.message_id))
  node?.focus({ preventScroll: true })
  const destination = node?.querySelector('mark') || node
  destination?.scrollIntoView({ block: 'center', behavior: 'auto' })
  notice.value = `已定位来源聊天，第 ${page.value} 页。`
}
async function focusTarget(request) {
  if (!request) return
  if (request.field_key && props.fields.some(field => field.value === request.field_key) && request.field_key !== props.fieldKey) emit('update:fieldKey', request.field_key)
  notice.value = '请在下方聊天原文中选中文字，再点击“引用选中文字”。'
  await nextTick()
  targetHeading.value?.focus({ preventScroll: true })
  targetHeading.value?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
}
function turnPage(next) {
  const nextPage = Number(next)
  if (props.busy || !Number.isInteger(nextPage) || nextPage < 1 || nextPage > pages.value || nextPage === page.value) return
  focusVersion++; selection.value = null; page.value = nextPage
}
watch(search, () => { page.value = 1; selection.value = null })
watch(pages, value => { if (page.value > value) page.value = value })
watch([page, search], () => {
  selection.value = null; notice.value = ''
  if (messageList.value) messageList.value.scrollTop = 0
}, { flush: 'post' })
watch([manualMessage, manualExcerpt], () => { manualOccurrence.value = '' })
watch(() => props.busy, busy => { if (busy) selection.value = null })
watch(() => props.focusRequest, focusSource, { deep: true, flush: 'post' })
watch(() => props.selectionRequest, focusTarget, { deep: true, flush: 'post' })
onMounted(() => {
  document.addEventListener('selectionchange', captureSelection)
  if (props.focusRequest) focusSource(props.focusRequest)
  if (props.selectionRequest) focusTarget(props.selectionRequest)
})
onBeforeUnmount(() => { focusVersion++; document.removeEventListener('selectionchange', captureSelection) })
</script>

<template>
  <section ref="root" class="panel evidence-picker" :aria-busy="busy">
    <div class="evidence-picker__heading"><h3>原文与依据</h3><span class="muted">{{messages.length}} 条来源</span></div>
    <div ref="targetHeading" class="evidence-picker__target" tabindex="-1">
      <span>当前补充依据</span>
      <strong>{{target?.label || '请选择关联内容'}}</strong>
      <p v-if="target?.preview">{{target.preview}}</p>
      <small v-if="target?.description">{{target.description}}</small>
    </div>
    <details class="evidence-picker__change">
      <summary>更换关联内容</summary>
      <label>引用用于说明<select :value="fieldKey" :disabled="busy" aria-label="引用用于说明" @change="emit('update:fieldKey', $event.target.value)"><option value="" disabled>请选择关联内容</option><option v-for="field in fields" :key="field.value" :value="field.value">{{field.label}}</option></select></label>
    </details>
    <p class="evidence-picker__hint">选中聊天中的文字即可引用，原文位置会自动记录。</p>
    <p v-if="notice" class="evidence-picker__notice" role="status">{{notice}}</p>
    <label class="evidence-picker__search"><Search :size="15" aria-hidden="true"/><input v-model="search" type="search" :disabled="busy" aria-label="搜索来源聊天" placeholder="搜索发送人或聊天原文"></label>
    <Pagination class="evidence-picker__pagination" aria-label="来源聊天分页" :page="page" :total="filtered.length" :page-size="pageSize" :disabled="busy" @change="turnPage"/>
    <div ref="messageList" class="evidence-picker__messages" role="region" aria-label="聊天原文列表" tabindex="0">
      <article v-for="message in visible" :key="message.id" class="evidence-picker__message" :class="{ 'is-located': String(highlight?.message_id) === String(message.id), 'is-deleted': message.is_deleted }">
        <div class="evidence-picker__author"><strong>{{message.sender_name_raw || '未知成员'}}</strong><time>{{formatDate(message.sent_at)}}</time></div>
        <small v-if="message.source_filename" class="evidence-picker__filename">{{message.source_filename}}</small>
        <pre :ref="element => setSourceNode(message.id, element)" :data-evidence-raw="message.id" :tabindex="busy ? -1 : 0" :aria-disabled="busy" :aria-label="`${message.sender_name_raw || '未知成员'}的聊天原文，可按 Shift 加方向键选择文字`" @keydown="extendKeyboardSelection" @mouseup="captureSelection" @keyup="captureSelection"><template v-for="(part, index) in messageParts(message)" :key="index"><mark v-if="part.selected">{{part.text}}</mark><template v-else>{{part.text}}</template></template></pre>
        <p v-if="message.is_deleted" class="evidence-picker__deleted">来源已删除，可核对历史原文，不可新增引用。</p>
        <div v-else class="evidence-picker__message-actions">
          <button v-if="selection?.message_id === message.id" type="button" class="small primary" :disabled="busy || !target" @pointerdown.prevent @click="addSelection(message)"><Quote :size="13"/>引用选中文字</button>
          <button v-else type="button" class="small" :disabled="busy || !target || !message.raw_text" @click="addWhole(message)">引用整条消息</button>
          <span v-if="selection?.message_id === message.id" class="evidence-picker__selection-hint">已选 {{Array.from(selection.exact_excerpt).length}} 字</span>
        </div>
      </article>
      <p v-if="!visible.length" class="evidence-picker__empty">{{search ? '没有匹配的聊天原文，请更换关键词。' : '暂无来源聊天。'}}</p>
    </div>
    <details class="evidence-picker__manual">
      <summary>手动粘贴原文</summary>
      <label>来源聊天<SearchSelect v-model="manualMessage" :options="manualOptions" :disabled="busy" aria-label="手动引用的来源聊天" placeholder="搜索发送人或原文关键词"/></label>
      <label>需要引用的原文<textarea v-model="manualExcerpt" rows="3" :disabled="busy" aria-label="手动粘贴的原文" placeholder="原样粘贴，需要与来源聊天中的文字完全一致"></textarea></label>
      <p v-if="manualSource && manualExcerpt && !manualMatches.length" class="evidence-picker__validation" role="status">未找到完全一致的原文，请检查空格、换行或选择的来源消息。</p>
      <label v-if="manualMatches.length > 1">找到 {{manualMatches.length}} 处相同原文，请确认位置<select v-model="manualOccurrence" :disabled="busy" aria-label="相同原文的位置"><option value="" disabled>请选择要引用的位置</option><option v-for="match in manualMatches" :key="match.occurrence" :value="match.occurrence">{{matchLabel(match)}}</option></select></label>
      <button type="button" class="small" :disabled="!manualReady" @click="addManual">添加原文引用</button>
    </details>
  </section>
</template>
