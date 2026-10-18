<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { Sparkles, RefreshCw, FileText } from 'lucide-vue-next'
import { api } from '../api'
import ExtractionOptions from './ExtractionOptions.vue'
import Pagination from './Pagination.vue'
import RefreshStatus from './RefreshStatus.vue'
import '../file-processing.css'

const props = defineProps({
  batch: { type: Object, required: true },
  profiles: { type: Array, default: () => [] },
  profile: { type: String, default: 'local' },
  mode: { type: String, default: 'both' },
  canGenerate: Boolean,
  busy: Boolean,
  latestJob: { type: Object, default: null },
})
const emit = defineEmits(['update:profile', 'update:mode', 'generate', 'open-record', 'changed'])
const job = ref(null), records = ref([]), recordsPage = ref(1), recordsTotal = ref(0)
const checking = ref(false), recordsLoading = ref(false), actionBusy = ref(false)
const loadError = ref(''), recordsError = ref(''), actionError = ref('')
const lastSuccess = ref('')
const activeStates = ['queued', 'running', 'cancel_requested']
const retryStates = ['failed', 'partial_failed', 'cancelled']
const stateLabels = { queued: '排队中', running: '正在生成', cancel_requested: '正在取消', succeeded: '已完成', failed: '生成失败', partial_failed: '部分完成', cancelled: '已取消' }
const reviewLabels = { draft: '草稿', in_review: '待审核', approved: '已批准', rejected: '已驳回', superseded: '已替代' }
const resultLabels = { created: '新增草稿', updated: '更新草稿', reused: '复用已有版本', manual_review_required: '已有人工草稿或待审核内容，已保留' }
const active = computed(() => !!job.value && activeStates.includes(job.value.state))
const canWrite = computed(() => props.canGenerate && !props.batch.is_deleted && !!props.batch.confirmed_at)
const configured = computed(() => !!props.profiles.find(item => item.id === props.profile)?.configured)
const locked = computed(() => props.busy || actionBusy.value)
const canRetry = computed(() => canWrite.value && retryStates.includes(job.value?.state))
const checkpoint = computed(() => job.value?.checkpoint || {})
// The checkpoint is task history; manual message processing updates the file counts.
const needsReview = computed(() => props.batch.message_counts?.needs_review)
const progress = computed(() => {
  const cp = checkpoint.value
  if (cp.extraction_total) return { label: '生成草稿', done: cp.extraction_done || 0, total: cp.extraction_total }
  if (cp.messages_total) return { label: '整理聊天', done: cp.messages_done || 0, total: cp.messages_total }
  return null
})
let alive = true, context = 0, jobRequest = 0, recordsRequest = 0, pollTimer

function date(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '' }
function modeLabel(value) { return ({ both: '工单与 QA', ticket: '仅工单', qa: '仅 QA' })[value] || '工单与 QA' }
function clearPoll() { if (pollTimer) clearTimeout(pollTimer); pollTimer = undefined }
function current(token) { return alive && context === token }
function schedulePoll() {
  clearPoll()
  if (alive && active.value) pollTimer = setTimeout(() => loadLatest(true), 8000)
}

async function loadRecords(next = 1) {
  if (!job.value) return
  const token = context, request = ++recordsRequest, jobId = job.value.id
  recordsLoading.value = true; recordsError.value = ''
  try {
    const result = await api(`/jobs/${jobId}/records?page=${next}&page_size=10`)
    if (!current(token) || request !== recordsRequest || job.value?.id !== jobId) return
    records.value = result.items; recordsPage.value = result.page; recordsTotal.value = result.total
  } catch (error) {
    if (current(token) && request === recordsRequest && job.value?.id === jobId) recordsError.value = error.message
  } finally {
    if (current(token) && request === recordsRequest) recordsLoading.value = false
  }
}

function applyJob(next) {
  const previous = job.value
  const changedJob = previous?.id !== next?.id
  const changedRun = changedJob || previous?.state !== next?.state || previous?.version !== next?.version
  if (changedJob) {
    ++recordsRequest; records.value = []; recordsPage.value = 1; recordsTotal.value = 0
    recordsError.value = ''; recordsLoading.value = false
  }
  job.value = next
  if (next && !activeStates.includes(next.state) && changedRun) loadRecords(changedJob ? 1 : recordsPage.value)
  if (previous && activeStates.includes(previous.state) && next && !activeStates.includes(next.state)) emit('changed')
  schedulePoll()
}

async function loadLatest(quiet = false) {
  if (!props.batch?.id || !alive || actionBusy.value) { schedulePoll(); return }
  clearPoll()
  const token = context, request = ++jobRequest, batchId = props.batch.id
  if (!quiet) checking.value = true
  try {
    const result = await api(`/jobs?batch_id=${encodeURIComponent(batchId)}&page=1&page_size=1`)
    if (!current(token) || request !== jobRequest) return
    loadError.value = ''; lastSuccess.value = new Date().toISOString()
    applyJob(result.items[0] || null)
  } catch (error) {
    if (current(token) && request === jobRequest) loadError.value = error.message
  } finally {
    if (current(token) && request === jobRequest) { checking.value = false; schedulePoll() }
  }
}

async function jobAction(action) {
  if (!canWrite.value || locked.value || !job.value) return
  const target = job.value
  if (action === 'retry' && !retryStates.includes(target.state)) return
  if (action === 'cancel' && !['queued', 'running'].includes(target.state)) return
  const token = context
  ++jobRequest; clearPoll(); checking.value = false; actionBusy.value = true; actionError.value = ''
  try {
    const result = await api(`/jobs/${target.id}/${action}`, { method: 'POST', version: target.version })
    if (!current(token)) return
    applyJob(result); emit('changed')
  } catch (error) {
    if (current(token)) actionError.value = error.message
  } finally {
    if (current(token)) {
      actionBusy.value = false
      // Re-read the server state after version conflicts or a task finishing during this action.
      await loadLatest(true)
    }
  }
}

function generate() {
  if (canWrite.value && configured.value && !locked.value && !checking.value && !loadError.value && !active.value) emit('generate')
}

watch(() => props.batch.id, () => {
  ++context; ++jobRequest; ++recordsRequest; clearPoll()
  job.value = null; records.value = []; recordsPage.value = 1; recordsTotal.value = 0
  checking.value = false; recordsLoading.value = false; actionBusy.value = false
  loadError.value = ''; recordsError.value = ''; actionError.value = ''
  lastSuccess.value = ''
  if (props.latestJob?.batch_id === props.batch.id) applyJob(props.latestJob)
  loadLatest()
}, { immediate: true })

watch(() => props.latestJob, next => {
  if (!next || next.batch_id !== props.batch.id) return
  ++jobRequest; checking.value = false; loadError.value = ''; actionError.value = ''; lastSuccess.value = new Date().toISOString()
  applyJob(next)
})

onUnmounted(() => { alive = false; ++context; ++jobRequest; ++recordsRequest; clearPoll() })
</script>

<template>
  <section class="panel file-processing" aria-label="生成草稿">
    <div class="file-processing-heading">
      <div>
        <h3><Sparkles :size="18"/>生成草稿</h3>
        <p class="hint">整理聊天中的问题与回答，生成可核对原文的草稿，确认后再提交审核。</p>
      </div>
      <span v-if="job" class="badge" :class="job.state">{{ stateLabels[job.state] || job.state }}</span>
    </div>

    <div v-if="canWrite" class="file-processing-start">
      <ExtractionOptions :profiles="profiles" :profile="profile" :mode="mode" :disabled="locked || active" @update:profile="emit('update:profile', $event)" @update:mode="emit('update:mode', $event)"/>
      <div class="file-processing-actions">
        <button v-if="active" class="primary" disabled><RefreshCw :size="15" class="spin"/>{{ stateLabels[job.state] || '处理中' }}</button>
        <template v-else-if="canRetry">
          <button class="primary" :disabled="locked || checking" @click="jobAction('retry')"><RefreshCw :size="15"/>{{ actionBusy ? '正在处理…' : '从断点继续' }}</button>
          <button class="small" :disabled="locked || checking || !configured || !!loadError" @click="generate">处理待整理消息</button>
        </template>
        <button v-else class="primary" :disabled="locked || checking || !configured || !!loadError" @click="generate"><Sparkles :size="15"/>{{ busy ? '正在启动…' : job ? '处理待整理消息' : '生成草稿' }}</button>
        <button v-if="job && ['queued', 'running'].includes(job.state)" class="small" :disabled="locked" @click="jobAction('cancel')">取消任务</button>
      </div>
      <p v-if="canRetry" class="hint">“从断点继续”沿用原任务的模型和生成内容；调整选项仅用于发起新的生成请求。</p>
    </div>
    <p v-else-if="batch.is_deleted" class="hint">文件已删除，仍可查看历史任务和生成记录；恢复文件后可继续生成。</p>
    <p v-else-if="!batch.confirmed_at" class="hint">确认导入后即可生成草稿。</p>

    <p v-if="checking && !job" class="hint" role="status">正在读取处理进度…</p>
    <RefreshStatus v-if="loadError || lastSuccess" :error="loadError" :last-success="lastSuccess" :busy="checking || actionBusy" @retry="loadLatest()"/>
    <p v-if="actionError" class="file-processing-error" role="alert">{{ actionError }}</p>

    <div v-if="job" class="file-processing-status" aria-live="polite">
      <p class="muted">{{ active ? '本次任务' : '最近一次任务' }}：{{ job.model_profile_snapshot?.id === 'external' ? '外部模型' : '本地模型' }} · {{ modeLabel(job.mode) }}<span v-if="job.created_at"> · {{ date(job.created_at) }}</span></p>
      <div v-if="active && progress" class="file-processing-progress">
        <div><span>{{ progress.label }}</span><span>{{ progress.done }} / {{ progress.total }}</span></div>
        <progress :value="Math.min(progress.done, progress.total)" :max="progress.total" :aria-label="progress.label"/>
      </div>
      <p v-if="active && checkpoint.map_parts_total" class="hint">正在分段处理较长的问题：{{ checkpoint.map_parts_done || 0 }} / {{ checkpoint.map_parts_total }}</p>
      <p v-if="active && !loadError" class="hint">进度会自动更新。可以离开此页，稍后回到文件查看结果。</p>
      <p v-if="job.error_summary" class="file-processing-error">{{ job.error_summary }}</p>
      <template v-if="!active && !batch.is_deleted && Number.isInteger(needsReview)">
        <p v-if="needsReview > 0" class="warning-text file-processing-review-hint">当前还有 {{ needsReview }} 条消息需要人工归属，可在下方聊天记录中筛选核对。</p>
        <p v-else class="file-processing-review-hint file-processing-review-complete">当前没有需要人工归属的消息。</p>
      </template>
    </div>

    <div v-if="job && !active" class="file-processing-results">
      <div class="section-line"><h3><FileText :size="16"/>生成结果<span v-if="!recordsLoading && !recordsError" class="muted">{{ recordsTotal }} 条</span></h3><span class="muted">原文、证据和审核记录均保留</span></div>
      <p v-if="recordsLoading" class="hint" role="status">正在读取生成结果…</p>
      <div v-if="recordsError" class="file-processing-error" role="alert"><span>读取结果失败：{{ recordsError }}</span><button class="small" :disabled="recordsLoading" @click="loadRecords(recordsPage)">重新加载</button></div>
      <div v-for="record in records" :key="record.record_kind + record.revision_id" class="file-draft-row">
        <div><strong>{{ record.title || '未命名草稿' }}</strong><small>{{ record.record_kind === 'ticket' ? '工单' : 'QA' }} · {{ record.record_no }} · 版本 {{ record.revision_no }} · {{ resultLabels[record.action] || '生成记录' }}</small></div>
        <span class="badge" :class="record.state">{{ record.is_deleted ? '已删除' : reviewLabels[record.state] || record.state }}</span>
        <button class="small" :disabled="busy || record.is_deleted" @click="emit('open-record', record)">{{ record.state === 'draft' ? '核对草稿' : '查看此版本' }}</button>
      </div>
      <p v-if="!recordsLoading && !recordsError && !records.length" class="hint">{{ job.state === 'succeeded' ? '本次未生成工单或 QA。可核对下方聊天内容与消息归属；若恢复了过滤消息，可点击“处理待整理消息”。' : '本次尚未生成记录。可查看上方处理情况，继续任务后会在这里展示结果。' }}</p>
      <Pagination v-if="recordsTotal > 10" :page="recordsPage" :total="recordsTotal" :disabled="recordsLoading || locked" @change="loadRecords"/>
    </div>
    <p v-else-if="!job && !checking && !loadError" class="hint">{{ canWrite ? '生成完成后，草稿会直接显示在这里。' : '此文件暂无生成任务。' }}</p>
  </section>
</template>
