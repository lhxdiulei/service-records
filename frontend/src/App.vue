<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { LayoutDashboard, MessagesSquare, Tickets, BookOpen, ClipboardCheck, Settings, LogOut, Plus, Upload, Search, ArrowLeft, Check, X, ChevronRight, RefreshCw, Sparkles, FileText, ShieldCheck, Menu } from 'lucide-vue-next'
import { api, loadCsrf, resetCsrf } from './api'
import Pagination from './components/Pagination.vue'
import SearchSelect from './components/SearchSelect.vue'
import ExtractionOptions from './components/ExtractionOptions.vue'
import FileProcessing from './components/FileProcessing.vue'
import UserManagement from './components/UserManagement.vue'
import DashboardMetrics from './components/DashboardMetrics.vue'
import { confirmThenExtract, saveThenSubmit } from './workflows.js'
import EvidencePicker from './components/EvidencePicker.vue'
import ContributorPicker from './components/ContributorPicker.vue'
import MoreActions from './components/MoreActions.vue'
import { earliestVisibleMessage } from './editor-assist.js'
import { fieldLabel } from './field-labels.js'
import { useReviewDrafts } from './review-drafts.js'
import RefreshStatus from './components/RefreshStatus.vue'
import ImportWarnings from './components/ImportWarnings.vue'
import ReviewHistory from './components/ReviewHistory.vue'
import './editor-assist.css'
import './workflow-feedback.css'
import { useMobileShell } from './mobile-shell.js'

const user = ref(null), ready = ref(false), page = ref('dashboard'), loading = ref(false), error = ref(''), success = ref('')
const tickets = ref([]), qas = ref([]), issues = ref([]), messages = ref([]), people = ref([]), imports = ref([]), jobs = ref([]), profiles = ref([])
const userManagementReload = ref(0)
const recentTickets = ref([])
const reviews = ref([]), overview = reactive({ tickets: 0, official_tickets: 0, qa: 0, official_qa: 0, reviews: 0, unassigned_messages: 0 })
const pageSize = 10
const pagers = reactive(Object.fromEntries(['messages','tickets','qa','jobs','reviews','imports','jobRecords','source','evidence','claims','actions','reviewHistory','notes'].map(key => [key, { page: 1, total: 0 }])))
const collections = { messages, tickets, qa: qas, jobs, reviews, imports }
const trash = reactive({ messages: false, imports: false, tickets: false, qa: false })
const deletion = ref(null), lastDeleted = ref(null), jobResults = ref(null), generatedRecords = ref([])
const listBusy = reactive({}), requests = {}
const listQueries = reactive({ messages: '', tickets: '', qa: '' })
const query = computed({ get: () => listQueries[page.value] || '', set: value => { if (page.value in listQueries) listQueries[page.value] = value } })
const disposition = ref(''), selected = ref([]), totalMessages = ref(0)
const toolsOpen = ref(false), qaCreateOpen = ref(false)
const listScroll = {}, detailReturn = ref(null)
let fileListScroll = 0
const currentFile = ref(null), fileQuery = ref(''), fileStatus = ref('all')
const latestFileJob = ref(null)
const preview = ref(null), acceptWarnings = ref(false), uploadFile = ref(null), assignTitle = ref(''), assignIssue = ref(''), assignRelation = ref('context'), ignoreReason = ref('与当前客服问题无关')
const previewScreening = ref('all'), previewNotice = ref('')
const { isMobile, mobileNavOpen, navToggle, navPanel, navClose, appDialog, backgroundBlocked, toggleMobileNav, closeMobileNav, navKeydown, closeAppDialog, dialogKeydown, rememberDialogTrigger } = useMobileShell({ preview, deletion, jobResults, loading })
const previewFocusIndex = ref(null), lastAssignment = ref(null)
const jobRefresh = reactive({ error: '', lastSuccess: '' })
const messageAssignIssue = ref('__new__')
const screeningSummary = computed(() => preview.value?.screening_summary || preview.value?.batch?.screening_summary || null)
const detail = ref(null), kind = ref('ticket'), revisionId = ref(''), editing = ref(false), bindings = ref([]), incompleteAccepted = ref(false), fieldKey = ref('problem')
const reviewDraftKey = computed(() => user.value && detail.value ? `${user.value.id}:${kind.value}:${detail.value.object.id}:${revisionId.value || 'new'}` : '')
const reviewDrafts = useReviewDrafts(reviewDraftKey)
const comment = reviewDrafts.comment
const hasUnsavedInput = computed(() => editing.value || !!comment.value.trim())
const evidenceFocus = ref(null), evidenceSelection = ref(null), changedEvidenceFields = ref([])
const dateOptionsOpen = ref(false), claimsOpen = ref(false), bindingsOpen = ref(false)
let evidenceRequest = 0
const form = reactive({}), loginForm = reactive({ username: 'admin', password: '' })
const qaSource = ref(''), modelProfile = ref('local'), extractMode = ref('both')
const nav = [{ id: 'dashboard', label: '工作台', icon: LayoutDashboard }, { id: 'messages', label: '聊天记录', icon: MessagesSquare }, { id: 'tickets', label: '服务工单', icon: Tickets }, { id: 'qa', label: '知识 QA', icon: BookOpen }, { id: 'reviews', label: '审核中心', icon: ClipboardCheck }, { id: 'jobs', label: 'AI 任务', icon: Sparkles }, { id: 'settings', label: '设置', icon: Settings }]
const primaryNav = nav.filter(item => !['jobs','settings'].includes(item.id))
const secondaryNav = nav.filter(item => ['jobs','settings'].includes(item.id))
const activeFilterCount = computed(() => page.value === 'messages' ? currentFile.value ? Number(!!disposition.value) + Number(trash.messages) : Number(fileStatus.value !== 'all') + Number(trash.imports) : Number(!!trash[page.value]))
const detailReturnLabel = computed(() => page.value === 'messages' && currentFile.value ? '返回本文件' : page.value === 'dashboard' ? '返回工作台' : '返回' + (page.value === 'jobs' ? '任务' : page.value === 'reviews' ? '审核' : kind.value === 'ticket' ? '工单' : '知识') + '列表')
const states = { draft: '草稿', in_review: '待审核', approved: '已批准', rejected: '已驳回', superseded: '已替代', open: '待处理', in_progress: '处理中', waiting_customer: '待客户回复', waiting_internal: '待内部处理', answered: '已回答', resolved: '已解决', cancelled: '已取消', unknown: '待确认', queued: '排队中', running: '运行中', succeeded: '已完成', failed: '失败', partial_failed: '部分失败', cancel_requested: '取消中', pending: '待归属', assigned: '已归属', ignored: '已忽略', needs_review: '需人工判断', supported: '有明确答案', no_answer: '暂无答案', conflict: '存在冲突', missing_context: '缺少上下文' }
const roleNames = { admin: '管理员', agent: '客服', reviewer: '审核员', customer: '客户', support: '客服', unknown: '未确认', other: '其他' }
const currentRevision = computed(() => detail.value?.revisions.find(r => r.id === revisionId.value))
const pendingReviews = computed(() => reviews.value)
const filteredObjects = computed(() => page.value === 'qa' ? qas.value : tickets.value)
const visibleMessages = computed(() => messages.value)
const canReview = computed(() => ['admin', 'reviewer'].includes(user.value?.role))
const canImport = computed(() => ['admin', 'agent'].includes(user.value?.role))
const isAdmin = computed(() => user.value?.role === 'admin')
const modelConfigured = computed(() => !!profiles.value.find(p => p.id === modelProfile.value)?.configured)
const needsDraftSave = computed(() => !currentRevision.value || editing.value || currentRevision.value.stale || currentRevision.value.state !== 'draft')
const canSubmitDraft = computed(() => !currentRevision.value || editing.value || currentRevision.value.stale || ['draft','rejected'].includes(currentRevision.value.state))
const issueOptions = computed(() => issues.value.map(i => ({ value: i.id, label: i.label, description: `创建于 ${date(i.created_at)}`, searchText: i.id, active: i.lifecycle === 'active' })))
const activeIssueOptions = computed(() => issueOptions.value.filter(i => i.active))
const assignmentOptions = computed(() => [{ value: '__new__', label: '建立新问题', description: '为所选消息新建一个问题' }, ...activeIssueOptions.value])
const sourceMessageOptions = computed(() => (detail.value?.source_messages || []).map(m => ({ value: m.id, label: `${m.sender_name_raw || '未知成员'} · ${date(m.sent_at)}`, description: `${m.is_deleted ? '来源已删除 · ' : ''}${m.raw_text.replace(/\s+/g, ' ').slice(0, 120)}`, searchText: `${m.raw_text} ${m.source_filename || ''}`, deleted: m.is_deleted })))
const firstVisibleMessage = computed(() => earliestVisibleMessage(detail.value?.source_messages || []))
const questionTimeUncertain = computed(() => (detail.value?.source_messages || []).some(m => !m.is_deleted && m.relation === 'question' && (!m.sent_at || !Number.isFinite(Date.parse(m.sent_at)))))
const firstQuestionSuggestion = computed(() => questionTimeUncertain.value ? null : earliestVisibleMessage((detail.value?.source_messages || []).filter(m => m.relation === 'question')))
const questionDateMessage = computed(() => (detail.value?.source_messages || []).find(m => m.id === form.first_question_message_id && !m.is_deleted && m.sent_at && Number.isFinite(Date.parse(m.sent_at))))
const questionDateOptions = computed(() => sourceMessageOptions.value.filter(option => (detail.value?.source_messages || []).some(m => m.id === option.value && !m.is_deleted && m.sent_at && Number.isFinite(Date.parse(m.sent_at)))))
const dateNeedsReview = computed(() => !firstVisibleMessage.value || form.date_basis === 'first_visible_context' || !questionDateMessage.value)
const displayedTicketDate = computed(() => {
  const r = currentRevision.value
  if (r && !editing.value) {
    if (r.ticket_date) return r.ticket_date
    const snapshot = r.date_basis === 'first_question' ? r.first_question_at : r.first_visible_at
    if (snapshot) return date(snapshot)
  }
  return date(form.date_basis === 'first_question' ? questionDateMessage.value?.sent_at : firstVisibleMessage.value?.sent_at)
})
const displayedDateSource = computed(() => {
  const id = form.date_basis === 'first_question' ? form.first_question_message_id : currentRevision.value && !editing.value ? form.first_visible_message_id : firstVisibleMessage.value?.id
  return (detail.value?.source_messages || []).find(m => m.id === id)
})
const editorClaims = computed(() => (kind.value === 'ticket' ? form.claims : form.answer_claims) || [])
const claimPrefix = computed(() => kind.value === 'ticket' ? 'claims.' : 'answer_claims.')
const claimProblems = computed(() => editorClaims.value.filter(c => !c.text.trim() || evidenceState(claimPrefix.value + c.claim_key) !== 'supported').length)
const evidenceProblems = computed(() => bindings.value.filter(b => b.relation === 'contradicts' || !fieldOptions.value.some(f => f.value === b.field_key) || !(detail.value?.source_messages || []).some(m => m.id === b.message_id && !m.is_deleted)).length)
const fieldOptions = computed(() => {
  const main = kind.value === 'ticket' ? [
    { value: 'problem', label: fieldLabel('problem'), description: '用原文证明客户提出了什么问题。', preview: form.problem },
    { value: 'handling_summary', label: fieldLabel('handling_summary'), description: '用原文证明已经进行的排查、沟通或处理。', preview: form.handling_summary },
    { value: 'current_conclusion', label: fieldLabel('current_conclusion'), description: '用原文证明目前得到的答复或处理结果。', preview: form.current_conclusion },
    { value: 'status', label: fieldLabel('status'), description: '用原文证明“已回答”“已解决”等处理状态有依据。', preview: label(form.status) },
  ] : [
    { value: 'question', label: fieldLabel('question'), description: '用原文证明这条 QA 对应的客户问题。', preview: form.question },
    { value: 'answer', label: fieldLabel('answer'), description: '用原文证明 QA 中的回答有依据。', preview: form.answer },
  ]
  const prefix = kind.value === 'ticket' ? 'claims.' : 'answer_claims.'
  const facts = (kind.value === 'ticket' ? form.claims : form.answer_claims) || []
  return [...main, ...facts.map((c, i) => ({ value: prefix + c.claim_key, label: `关键事实 ${i + 1}：${c.text?.trim().slice(0, 32) || '待填写内容'}${c.text?.trim().length > 32 ? '…' : ''}`, description: '用原文证明这条具体说法，编号与内容编辑区的关键事实一致。', preview: c.text, searchText: c.text }))]
})
function evidenceFieldLabel(key) {
  return fieldOptions.value.find(f => f.value === key)?.label || (/^(claims|answer_claims)\./.test(key) ? '已移除的关键事实（请核对这条证据）' : '其他内容依据')
}
function fieldEvidence(key) { return bindings.value.filter(b => b.field_key === key) }
function evidenceState(key) {
  const linked = fieldEvidence(key)
  if (!linked.length && kind.value === 'ticket' && ['problem','handling_summary','current_conclusion','status'].includes(key)) return 'optional'
  if (linked.some(b => b.relation === 'contradicts')) return 'conflict'
  if (changedEvidenceFields.value.includes(key) && linked.length) return 'changed'
  return linked.some(b => b.relation === 'supports' && (detail.value?.source_messages || []).some(m => m.id === b.message_id && !m.is_deleted)) ? 'supported' : 'missing'
}
function evidenceText(key) {
  const state = evidenceState(key), count = fieldEvidence(key).length
  return state === 'optional' ? '关联原文（可选）' : state === 'conflict' ? `存在矛盾 · ${count} 条依据` : state === 'changed' ? `内容已改 · 核对 ${count} 条依据` : count ? `原文依据 ${count} 条` : '补充原文依据'
}
function markFieldChanged(key) { editing.value = true; if (!changedEvidenceFields.value.includes(key)) changedEvidenceFields.value.push(key) }
function locateSource(binding) {
  evidenceFocus.value = { message_id: binding.message_id || binding.id, start_cp: binding.start_cp, end_cp: binding.end_cp, nonce: ++evidenceRequest }
}
function requestEvidence(key) {
  fieldKey.value = key; evidenceSelection.value = { field_key: key, nonce: ++evidenceRequest }
  const linked = fieldEvidence(key)[0]
  if (linked) locateSource(linked)
  else evidenceFocus.value = null
}
function changeDateBasis() {
  form.first_question_message_id = form.date_basis === 'first_question' ? firstQuestionSuggestion.value?.id || null : null
  incompleteAccepted.value = false; editing.value = true
}
function updateContributors(value) { form.contributors = value; editing.value = true }
function removeClaim(claim) {
  const key = claimPrefix.value + claim.claim_key
  const name = kind.value === 'ticket' ? 'claims' : 'answer_claims'
  form[name] = form[name].filter(c => c.claim_key !== claim.claim_key)
  bindings.value = bindings.value.filter(b => b.field_key !== key)
  editing.value = true
}

function date(v) { return v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '时间待确认' }
function label(v) { return states[v] || v }
function sourceNames(item) { return item.source_filenames?.join('、') || '聊天记录' }
function screeningReasons(summary) { return (summary?.reasons || []).map(r => `${r.label || '其他确定噪声'} ${r.count} 条`).join('；') }
const reasonNames = { nontext_only: '模型判为仅非文本', chitchat: '模型判为闲聊', system_message: '模型判为系统消息', ambiguous: '模型无法明确问题归属', insufficient_context: '上下文不足', missing_context: '上下文不足' }
function dispositionReason(m) {
  const text = (reasonNames[m.disposition_reason] || m.disposition_reason || (m.disposition === 'needs_review' ? '需人工核对归属' : '')) + (m.disposition_note ? '；' + m.disposition_note : '')
  return m.disposition_reason === 'nontext_only' && m.kind === 'text' ? text + '；此记录有文本，疑似误判，可重新核对' : text
}
function dispositionSource(m) { return ({ model_validated: 'AI判定', human: '人工处理', rule: '系统规则' })[m.disposition_source] || '' }
function localItems(items, key) { return (items || []).slice((pagers[key].page - 1) * pageSize, pagers[key].page * pageSize) }
async function fetchPage(key) {
  const generation = requests[key] = (requests[key] || 0) + 1
  if (key === 'messages' && !currentFile.value) {
    messages.value = []; pagers.messages.total = 0; totalMessages.value = 0; listBusy.messages = false
    return
  }
  const params = new URLSearchParams({ page: String(pagers[key].page), page_size: String(pageSize) })
  const path = key
  if (trash[key]) params.set('deleted', 'true')
  if (key === 'messages' && disposition.value) params.set('state', disposition.value)
  if (key === 'messages') params.set('batch_id', currentFile.value.id)
  if (key === 'imports') {
    if (fileQuery.value.trim()) params.set('q', fileQuery.value.trim())
    params.set('status', fileStatus.value)
  }
  if (listQueries[key]?.trim()) params.set('q', listQueries[key].trim())
  listBusy[key] = true
  try {
    const result = await api(`/${path}?${params}`)
    if (generation !== requests[key]) return
    const last = Math.max(1, Math.ceil(result.total / pageSize))
    if (pagers[key].page > last) { pagers[key].page = last; return await fetchPage(key) }
    collections[key].value = result.items; pagers[key].total = result.total
    if (key === 'jobs') { jobRefresh.error = ''; jobRefresh.lastSuccess = new Date().toISOString() }
    if (key === 'messages') totalMessages.value = result.total
  } catch (e) {
    if (key === 'jobs' && generation === requests[key]) jobRefresh.error = e.message
    throw e
  } finally { if (generation === requests[key]) listBusy[key] = false }
}
async function refreshJobs() {
  if (!user.value || loading.value || listBusy.jobs) return
  const request = (requests.jobs || 0) + 1
  try { await fetchPage('jobs') } catch (e) { if (request === requests.jobs) jobRefresh.error = e.message }
}
async function goPage(key, next) {
  const previous = pagers[key].page; pagers[key].page = next
  if (key === 'messages') selected.value = []
  try { await fetchPage(key) } catch (e) { pagers[key].page = previous; error.value = e.message }
}
async function loadOverview() {
  Object.assign(overview, await api('/overview'))
}
async function loadRecentTickets() { recentTickets.value = (await api('/tickets?page=1&page_size=6')).items }
async function run(fn) {
  if (loading.value) return
  loading.value = true; error.value = ''; success.value = ''
  try { await fn() } catch (e) { error.value = e.message } finally { loading.value = false }
}
function notice(text) { success.value = text }
async function refresh() {
  ;[issues.value, profiles.value] = await Promise.all([api('/issues'), api('/integrations/dify')])
  await Promise.all([loadMessages(), loadOverview(), ...(page.value === 'dashboard' ? [loadRecentTickets()] : []), ...['tickets','qa','jobs','reviews'].map(fetchPage)])
  if (page.value === 'settings' && user.value.role === 'admin') userManagementReload.value++
}
async function loadMessages() {
  if (currentFile.value) {
    const id = currentFile.value.id
    try {
      const batch = await api(`/imports/${id}`)
      if (currentFile.value?.id === id) { currentFile.value = batch; if (batch.is_deleted) trash.messages = true }
    } catch (e) {
      if (![403,404].includes(e.status)) throw e
      if (currentFile.value?.id === id) resetChatFile()
    }
  }
  await Promise.all(['messages','imports'].map(fetchPage)); selected.value = []
}
function resetChatFile() {
  latestFileJob.value = null; lastAssignment.value = null
  currentFile.value = null; requests.messages = (requests.messages || 0) + 1
  messages.value = []; selected.value = []; totalMessages.value = 0; pagers.messages.page = 1; pagers.messages.total = 0
  listQueries.messages = ''; disposition.value = ''; trash.messages = false; messageAssignIssue.value = '__new__'; assignTitle.value = ''
}
async function openChatFile(batch) {
  await run(() => enterChatFile(batch))
}
async function enterChatFile(batch, job = null) {
  const fresh = await api(`/imports/${batch.id}`)
  if (!currentFile.value && page.value === 'messages') fileListScroll = window.scrollY
  resetChatFile(); currentFile.value = fresh; latestFileJob.value = job
  page.value = 'messages'; detail.value = null; trash.messages = !!fresh.is_deleted; preview.value = null
  await fetchPage('messages'); window.scrollTo({top:0})
}
async function fileProcessingChanged() {
  if (!currentFile.value || detail.value || loading.value) return
  try { await Promise.all([loadMessages(), loadOverview()]) } catch (e) { error.value = `处理状态已更新，消息统计刷新失败：${e.message}` }
}
async function backToFiles() { resetChatFile(); await run(() => fetchPage('imports')); await nextTick(); window.scrollTo({top:fileListScroll}) }
function clearFilters() {
  const key = page.value === 'messages' && !currentFile.value ? 'imports' : page.value
  if (key === 'imports') { fileQuery.value = ''; fileStatus.value = 'all' }
  else { listQueries[key] = ''; if (key === 'messages') disposition.value = '' }
  trash[key] = false
  clearTimeout(key === 'imports' ? fileSearchTimer : searchTimer)
  selected.value = []; pagers[key].page = 1
  run(() => fetchPage(key))
}
async function changeTrash(key) { pagers[key].page = 1; selected.value = []; await fetchPage(key) }
function canDeleteDraft(r) { return !!r && ['draft','rejected','in_review'].includes(r.state) && (isAdmin.value || r.created_by === user.value?.id) }
function askDelete(recordKind, item) { deletion.value = { kind: recordKind, id: item.id, version: item.delete_version || 0, title: item.title || item.question || item.original_filename || item.raw_text?.slice(0,70) || item.ticket_no || item.qa_no || '这条记录' } }
async function deleteConfirmed() {
  await run(async () => { const d = deletion.value; const result = await api(`/records/${d.kind}/${d.id}`, {method:'DELETE',version:d.version}); lastDeleted.value = {...d,version:result.delete_version}; deletion.value = null; detail.value = null; if (d.kind==='import' && currentFile.value?.id===d.id) resetChatFile(); await refresh(); notice('已删除，可恢复；历史原文与证据保留') })
}
async function restoreRecord(recordKind,item) {
  await run(async () => { await api(`/records/${recordKind}/${item.id}/restore`,{method:'POST',version:item.delete_version}); lastDeleted.value = null; await refresh(); notice('已恢复记录') })
}
async function undoDelete() { const d=lastDeleted.value; if(d) await restoreRecord(d.kind,{id:d.id,delete_version:d.version}) }
async function restoreObject(objectKind,item) {
  if (item.latest_revision?.is_deleted && !item.parent_deleted) await restoreRecord(objectKind+'_draft',item.latest_revision)
  else await restoreRecord(objectKind,item)
}
async function showJobRecords(job,next=1) {
  const result = await api(`/jobs/${job.id}/records?page=${next}&page_size=${pageSize}`)
  jobResults.value = job; generatedRecords.value = result.items; pagers.jobRecords.page = result.page; pagers.jobRecords.total = result.total
}
async function openJobRecord(record) {
  await run(async () => { await openObject(record.record_kind,record.record_id,true,record.revision_id); jobResults.value = null })
}
function accountReauthenticate(message) { user.value = null; resetCsrf(); clearPrivateView(); error.value = message }
function navigateMetric(id) {
  if (loading.value) return
  if (id === 'messages') { fileQuery.value = ''; fileStatus.value = 'all'; trash.imports = false; openFileLibrary(); return }
  if (!['tickets','qa','reviews'].includes(id)) return
  if (id in listQueries) listQueries[id] = ''
  if (id in trash) trash[id] = false
  pagers[id].page = 1; navigate(id)
}
function navigate(id) {
  if (loading.value || !allowDiscardEdits()) return
  if (id === page.value && !detail.value) { closeMobileNav(); return }
  const fromMobileNav = isMobile.value && mobileNavOpen.value
  closeMobileNav(false)
  if (!detail.value) listScroll[page.value] = window.scrollY
  clearTimeout(searchTimer); clearTimeout(fileSearchTimer)
  page.value = id; detail.value = null; detailReturn.value = null; error.value = ''; selected.value = []
  if (['jobs','settings'].includes(id)) toolsOpen.value = true
  run(async () => {
    if (id === 'messages') await loadMessages()
    else if (id === 'dashboard') await Promise.all([loadRecentTickets(),loadOverview()])
    else if (collections[id]) await fetchPage(id)
    await nextTick(); window.scrollTo({top:listScroll[id] || 0})
    if (fromMobileNav) document.querySelector('.content h1')?.focus({ preventScroll: true })
  })
}
function openFileLibrary() {
  if (loading.value || !allowDiscardEdits()) return
  if (!detail.value) listScroll[page.value] = window.scrollY
  clearTimeout(searchTimer); clearTimeout(fileSearchTimer)
  page.value = 'messages'; detail.value = null; detailReturn.value = null; error.value = ''
  resetChatFile(); fileListScroll = 0
  run(() => fetchPage('imports'))
  window.scrollTo({top:0})
}
function allowDiscardEdits() { return !detail.value || !hasUnsavedInput.value || window.confirm('当前有未保存的正文或尚未提交的审核意见、内部备注。是否继续离开？意见会在本次登录期间按版本暂存；未保存的正文修改将丢失。') }
async function closeDetail() {
  if (loading.value || !allowDiscardEdits()) return
  const destination = detailReturn.value
  detail.value = null; detailReturn.value = null
  await nextTick(); window.scrollTo({top:destination?.scroll || 0})
}
function changeRevision(event) {
  if (!selectRevision(event.target.value)) event.target.value = revisionId.value
}
function selectRevision(id) {
  if (loading.value || !detail.value?.revisions.some(r => r.id === id)) return false
  if (id === revisionId.value) return true
  if (editing.value && !window.confirm('正文有未保存的修改，切换版本后将丢失，是否继续？审核意见和内部备注会按版本暂存。')) return false
  revisionId.value = id; setRevision(); return true
}
function protectUnsaved(event) { if (detail.value && hasUnsavedInput.value) { event.preventDefault(); event.returnValue = '' } }
async function loadPreview(id, next = 1, screening = previewScreening.value) {
  const params = new URLSearchParams({ page: String(next), page_size: String(pageSize), screening })
  const result = await api(`/imports/${id}/preview?${params}`)
  const last = Math.max(1, Math.ceil(result.total / pageSize))
  if (next > last) return await loadPreview(id, last, screening)
  preview.value = result; previewScreening.value = screening; previewFocusIndex.value = null
}
async function openPreview(id) { acceptWarnings.value = false; previewNotice.value = ''; await loadPreview(id, 1, 'all') }
async function changePreviewScreening(screening) { await run(() => loadPreview(preview.value.batch.id, 1, screening)) }
async function locatePreviewWarning(warning) {
  await run(async () => {
    await loadPreview(preview.value.batch.id, Math.floor(warning.index / pageSize) + 1, 'all')
    previewFocusIndex.value = warning.index
    await nextTick()
    const target = document.getElementById(`preview-source-${warning.index}`)
    target?.focus({ preventScroll: true }); target?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}
async function signIn() { await run(async () => { const result = await api('/auth/login', { method: 'POST', body: loginForm }); user.value = result.user; loginForm.password = ''; await refresh() }) }
function clearPrivateView() {
  closeMobileNav(false); jobRefresh.error=''; jobRefresh.lastSuccess=''; detail.value=null; detailReturn.value=null; deletion.value=null; lastDeleted.value=null; jobResults.value=null; preview.value=null; previewNotice.value=''; previewScreening.value='all'; resetChatFile(); fileQuery.value=''; fileStatus.value='all'; toolsOpen.value=false; qaCreateOpen.value=false; for (const key of Object.keys(trash)) trash[key]=false; for (const key of Object.keys(listQueries)) listQueries[key]=''; for (const key of Object.keys(listScroll)) delete listScroll[key]; for (const pager of Object.values(pagers)) pager.page=1; fileListScroll=0 }
async function logout() { if (!allowDiscardEdits()) return; await run(async () => { await api('/auth/logout', { method: 'POST' }); reviewDrafts.reset(); user.value = null; resetCsrf(); clearPrivateView() }) }
async function upload() {
  await run(async () => { if (!uploadFile.value) throw new Error('请选择文本文件'); const data = new FormData(); data.append('file', uploadFile.value); const result = await api('/imports', { method: 'POST', body: data }); await openPreview(result.batch.id); if (result.duplicate) notice('此文件已上传，已打开原有导入记录') })
}
async function confirmImport(generate = false) {
  await run(async () => {
    const b = preview.value.batch, next = preview.value.page
    const confirm = async () => {
      const confirmed = await api(`/imports/${b.id}/confirm`, { method: 'POST', version: b.version, body: { parse_version: b.parse_version, accept_warnings: acceptWarnings.value } })
      preview.value.batch = { ...b, ...confirmed }
      return confirmed
    }
    if (!generate) {
      if (!b.confirmed_at) await confirm()
      previewNotice.value = '聊天记录已导入，原文完整保留。可核对过滤结果，或直接生成草稿。'
      await Promise.all([loadMessages(), loadOverview(), loadPreview(b.id, next)])
      notice('聊天记录已导入，尚未启动 AI')
      return
    }
    if (!modelConfigured.value) throw new Error('当前模型尚未配置，可先选择“仅导入”，或调整生成选项')
    let job
    try {
      const result = await confirmThenExtract({ confirmed: !!b.confirmed_at, confirm, start: () => startExtraction(b.id, null) })
      job = result.job
    } catch (e) {
      if (e.confirmed) {
        previewNotice.value = '导入已完成，原文和筛选结果已保留。未能确认生成任务已启动，可查看文件进度或重试，无需重复导入。'
        await Promise.allSettled([loadPreview(b.id, next), loadMessages(), loadOverview()])
        throw new Error(`已导入，但生成请求未成功返回：${e.message}`)
      }
      throw e
    }
    previewNotice.value = '生成任务已创建，可在本文件查看进度和结果。'
    try { await enterChatFile(preview.value.batch, job) }
    catch (e) { throw new Error(`生成任务已创建，但文件页面加载失败；可重新打开文件查看进度：${e.message}`) }
    notice(job.reused_request ? '已找到相同任务，进度和草稿在本文件展示' : '已导入并开始生成草稿，完成后将在下方展示；正式发布仍需审核')
  })
}
async function restorePrefilterMessage(message) {
  await run(async () => {
    const id = preview.value.batch.id, next = preview.value.page
    await api(`/messages/${message.message_id}/disposition`, { method: 'PUT', version: message.disposition_version, body: { state: 'needs_review', reason: '人工恢复预筛选消息，重新参与归属与抽取' } })
    await Promise.all([loadPreview(id, next), loadMessages(), loadOverview()])
    previewNotice.value = '已恢复为待处理消息。可在此点击“生成草稿”重新整理；已有任务和结果不会自动更新。'
    notice('消息已恢复，需重新发起 AI 归属与抽取')
  })
}
async function assign() {
  await run(async () => {
    if (!selected.value.length) throw new Error('请先勾选消息')
    if (!messageAssignIssue.value) throw new Error('请选择一个已有问题，或选择“建立新问题”')
    const links = selected.value.map(id => ({ message_id: id, relation: assignRelation.value }))
    let ticketId, issueLabel
    if (messageAssignIssue.value !== '__new__') {
      const old = await api(`/issues/${messageAssignIssue.value}`); const merged = new Map(old.messages.map(m => [m.id, { message_id: m.id, relation: m.relation }])); links.forEach(m => merged.set(m.message_id, m))
      await api(`/issues/${messageAssignIssue.value}/messages`, { method: 'PATCH', version: old.issue.version, body: { messages: [...merged.values()] } })
      ticketId = old.ticket_id; issueLabel = old.issue.label
    } else {
      if (!assignTitle.value.trim()) throw new Error('请填写问题标题')
      const created = await api('/issues', { method: 'POST', body: { title: assignTitle.value, messages: links } })
      ticketId = created.ticket.id; issueLabel = created.issue.label
    }
    lastAssignment.value = { ticket_id: ticketId, label: issueLabel }; selected.value = []; assignTitle.value = ''
    // Assignment is already committed. A read failure must never suggest that
    // reassigning or creating another issue is required.
    const updates = await Promise.allSettled([refresh()])
    try { await openObject('ticket', ticketId, true); notice('消息已归属，已打开对应工单，可继续编辑草稿') }
    catch (e) { notice('消息已归属'); error.value = `对应工单暂时未能打开，可点击“打开所属工单”重试：${e.message}`; return }
    if (updates[0].status === 'rejected') error.value = `消息已归属并打开工单，部分列表未能更新：${updates[0].reason.message}`
  })
}
async function openAssignedIssue(issue) {
  if (loading.value || !allowDiscardEdits()) return
  await run(() => openObject('ticket', issue.ticket_id, true))
}
async function ignoreSelected() {
  await updateSelectedDisposition('ignored', ignoreReason.value.trim(), '已记录忽略原因')
}
async function recheckSelected() {
  await updateSelectedDisposition('needs_review', '人工要求重新核对此消息归属', '已标记待人工核对，可选择问题重新归属')
}
async function updateSelectedDisposition(state, reason, completedNotice) {
  if (listBusy.messages || !canImport.value || trash.messages) return
  const items = selected.value.map(id => messages.value.find(m => m.id === id)).filter(m => m && !m.is_deleted).map(m => ({ id: m.id, version: m.disposition_version }))
  if (!items.length || items.length !== selected.value.length || !reason) return
  await run(async () => {
    let completed = 0
    try {
      for (const item of items) {
        await api(`/messages/${item.id}/disposition`, { method: 'PUT', version: item.version, body: { state, reason } })
        completed++
      }
    } catch (e) {
      await Promise.allSettled([loadMessages(), loadOverview()])
      throw new Error(`已处理 ${completed} / ${items.length} 条，其余尚未完成：${e.message}。请核对最新状态后重试。`)
    }
    await refresh(); notice(completedNotice)
  })
}
function setRevision() {
  const r = currentRevision.value
  incompleteAccepted.value = false
  changedEvidenceFields.value = []; evidenceFocus.value = null; evidenceSelection.value = null
  Object.keys(form).forEach(k => delete form[k]); bindings.value = []; editing.value = false
  if (r) {
    if (kind.value === 'ticket') Object.assign(form, { title: r.title, problem: r.problem_text, impact: r.impact_text, handling_summary: r.handling_summary, current_conclusion: r.current_conclusion, status: r.status, first_visible_message_id: r.first_visible_message_id, first_question_message_id: r.first_question_message_id, date_basis: r.date_basis, claims: JSON.parse(JSON.stringify(r.claims)), next_actions: JSON.parse(JSON.stringify(r.next_actions)) })
    else Object.assign(form, { question: r.question, answer: r.answer || '', answer_state: r.answer_state, applicability: r.applicability, answer_claims: JSON.parse(JSON.stringify(r.answer_claims)), contributors: r.contributors.map(c => ({ participant_id: c.participant_id, contribution: c.contribution, evidence_span_ids: c.evidence_span_ids })) })
    bindings.value = r.evidence.map(e => ({ ...e }))
  } else if (kind.value === 'ticket') {
    const first = firstVisibleMessage.value, question = firstQuestionSuggestion.value
    Object.assign(form, { title: issues.value.find(i => i.id === detail.value.object.issue_id)?.label || '', problem: '', impact: '', handling_summary: '', current_conclusion: '', status: 'open', first_visible_message_id: first?.id, first_question_message_id: question?.id || null, date_basis: question ? 'first_question' : 'first_visible_context', claims: [], next_actions: [] })
    editing.value = true
  }
  fieldKey.value = kind.value === 'ticket' ? 'problem' : 'question'
  dateOptionsOpen.value = kind.value === 'ticket' && dateNeedsReview.value
  claimsOpen.value = claimProblems.value > 0 || (kind.value === 'qa' && !editorClaims.value.length)
  bindingsOpen.value = evidenceProblems.value > 0
}
async function openObject(objectKind, id, preservePage = false, preferredRevisionId = null) {
  if (!detail.value) detailReturn.value = { page: page.value, scroll: window.scrollY }
  kind.value = objectKind; if (!preservePage) page.value = objectKind === 'ticket' ? 'tickets' : 'qa'
  detail.value = await api(`/${objectKind === 'ticket' ? 'tickets' : 'qa'}/${id}`)
  for (const key of ['source','evidence','claims','actions','reviewHistory','notes']) pagers[key].page = 1
  revisionId.value = detail.value.revisions.find(r => r.id === preferredRevisionId)?.id || detail.value.revisions[0]?.id || ''; setRevision()
  people.value = detail.value.participants || []
  window.scrollTo({top:0})
}
async function createQA() {
  await run(async () => {
    const issue = issues.value.find(i => i.id === qaSource.value); if (!issue) throw new Error('请先选择一个来源问题')
    const result = await api('/qa', { method: 'POST', body: { issue_ids: [issue.id], content: { question: issue.label, answer: '', answer_state: 'no_answer', applicability: '', answer_claims: [], contributors: [] }, evidence: [] } })
    await refresh(); await openObject('qa', result.object.id); editing.value = true
  })
}
async function addEvidence(payload) {
  await run(async () => {
    const message = detail.value.source_messages.find(m => m.id === payload.message_id && !m.is_deleted)
    if (!message || !fieldOptions.value.some(f => f.value === payload.field_key)) throw new Error('请从当前记录的有效原文选择证据及对应内容')
    const e = await api('/evidence-spans', { method: 'POST', body: { message_id: message.id, exact_excerpt: payload.exact_excerpt, occurrence: payload.occurrence } })
    if (!bindings.value.some(b => b.field_key === payload.field_key && b.evidence_span_id === e.id)) {
      bindings.value.push({ evidence_span_id: e.id, field_key: payload.field_key, relation: 'supports', message_id: e.message_id, excerpt: payload.exact_excerpt, start_cp: e.start_cp, end_cp: e.end_cp })
      editing.value = true
    }
    locateSource(e)
    notice(`已关联「${evidenceFieldLabel(payload.field_key)}」的原文，保存草稿后生效`)
  })
}
function addClaim() { const key = kind.value === 'ticket' ? 'claims' : 'answer_claims'; const used = new Set(form[key].map(c => c.claim_key)); let i = 1; while (used.has('c' + i)) i++; form[key].push({ claim_key: 'c' + i, text: '' }); editing.value = true; claimsOpen.value = true; pagers.claims.page = Math.max(1, Math.ceil(form[key].length / pageSize)) }
function applyRevision(revision, replaces = null) {
  if (replaces && ['draft','in_review'].includes(replaces.state)) replaces.state = 'superseded'
  detail.value.revisions = [revision, ...detail.value.revisions.filter(r => r.id !== revision.id)]
  const previousComment = comment.value
  if (revisionId.value !== revision.id) reviewDrafts.clear()
  revisionId.value = revision.id; setRevision(); comment.value = previousComment
}
async function persistDraft() {
  const obj = detail.value.object, r = currentRevision.value, body = { expected_object_version: obj.version, base_revision_id: obj.current_revision_id, replaces_revision_id: r && r.state !== 'approved' && r.state !== 'superseded' ? r.id : null, content: JSON.parse(JSON.stringify(form)), evidence: bindings.value.map(e => ({ field_key: e.field_key, evidence_span_id: e.evidence_span_id, relation: e.relation })), change_reason: comment.value }
  if (kind.value === 'ticket') {
    if (!firstVisibleMessage.value) throw new Error('来源消息没有有效时间，请先核对来源时间后再保存')
    body.content.first_visible_message_id = firstVisibleMessage.value.id
    if (form.date_basis === 'first_question' && !questionDateMessage.value) { dateOptionsOpen.value = true; throw new Error('请在“校正日期依据”选择有效的原始提问；缺少原始提问时选择首次可见上下文') }
  }
  if (kind.value === 'qa') body.issue_ids = r.issue_ids
  const saved = await api(`/${kind.value === 'ticket' ? 'tickets' : 'qa'}/${obj.id}/revisions`, { method: 'POST', version: obj.version, body })
  applyRevision(saved, r)
  return saved
}
async function syncRecord(revision, message) {
  const objectKind = kind.value, id = detail.value.object.id
  try {
    await openObject(objectKind, id, true, revision.id)
    await Promise.all([loadOverview(), fetchPage(objectKind === 'ticket' ? 'tickets' : 'qa'), fetchPage('reviews')])
    notice(message)
  } catch (e) { notice(message); error.value = `操作已完成，但最新记录加载失败，请刷新：${e.message}` }
}
async function saveDraft() {
  await run(async () => {
    if (!needsDraftSave.value) { notice('当前草稿没有未保存的修改'); return }
    const saved = await persistDraft()
    await syncRecord(saved, '草稿已保存，尚未提交审核')
  })
}
async function sendReview(revision, action) {
  const obj = detail.value.object
  return await api(`/${kind.value === 'ticket' ? 'tickets' : 'qa'}/${obj.id}/revisions/${revision.id}/${action}`, { method: 'POST', version: revision.state_version, body: { expected_object_version: obj.version, expected_current_revision_id: obj.current_revision_id, comment: comment.value, accept_incomplete_start: incompleteAccepted.value } })
}
async function saveAndSubmit() {
  await run(async () => {
    let result
    try { result = await saveThenSubmit({ needsSave: needsDraftSave.value, save: persistDraft, submit: revision => sendReview(revision, 'submit'), revision: currentRevision.value }) }
    catch (e) {
      if (e.stage === 'submit') throw new Error(`${e.saved ? '草稿已保存，但未提交审核' : '未提交审核'}：${e.message}`)
      throw e
    }
    reviewDrafts.clear(); applyRevision(result.submission)
    await syncRecord(result.submission, '已提交审核，审核通过后才更新正式版本')
  })
}
async function review(action) {
  await run(async () => {
    if (editing.value) throw new Error('请先保存当前修改，再执行审核操作')
    const result = await sendReview(currentRevision.value, action)
    reviewDrafts.clear(); applyRevision(result)
    await syncRecord(result, { submit: '已提交审核', approve: '审核通过，已更新正式版本', reject: '已驳回，处理原因已记录' }[action])
  })
}
async function startExtraction(batchId, issueId) {
  const path = batchId ? `/imports/${batchId}/extractions` : `/issues/${issueId}/extractions`
  return await api(path, { method: 'POST', body: { mode: extractMode.value, profile: modelProfile.value } })
}
async function extract(batchId, issueId) {
  await run(async () => {
    const job = await startExtraction(batchId, issueId)
    if (batchId) {
      if (currentFile.value?.id === batchId) latestFileJob.value = job
      else {
        try { await enterChatFile({ id: batchId }, job) }
        catch (e) { throw new Error(`任务已创建，重新打开文件即可查看进度：${e.message}`) }
      }
    } else { pagers.jobs.page=1; await fetchPage('jobs'); page.value = 'jobs'; detail.value = null }
    notice(job.reused_request ? '已找到相同任务，可查看进度和已生成草稿' : '已开始生成草稿，正式发布仍需人工审核')
  })
}
async function jobAction(job, action) { await run(async () => { await api(`/jobs/${job.id}/${action}`, { method: 'POST', version: job.version }); await fetchPage('jobs') }) }
async function addNote() {
  await run(async () => {
    if (!comment.value.trim()) throw new Error('请填写备注')
    const note = await api(`/tickets/${detail.value.object.id}/notes`, { method: 'POST', version: detail.value.object.version, body: { note: comment.value } })
    detail.value.notes = [...(detail.value.notes || []), note]; comment.value = ''
    pagers.notes.page = Math.max(1, Math.ceil(detail.value.notes.length / pageSize))
    notice('内部备注已保存，正文修改仍保留在编辑区')
  })
}
function sessionExpired() { const wasSignedIn = !!user.value; user.value = null; resetCsrf(); clearPrivateView(); if (wasSignedIn) error.value = '会话已过期，请重新登录' }
let timer, searchTimer, fileSearchTimer
watch([fileQuery,fileStatus], () => {
  clearTimeout(fileSearchTimer)
  if (!user.value) return
  selected.value = []; pagers.imports.page = 1; requests.imports = (requests.imports || 0) + 1
  fileSearchTimer = setTimeout(async () => { try { await fetchPage('imports') } catch (e) { error.value = e.message } },250)
}, { flush: 'sync' })
watch(fieldOptions, options => {
  if (!options.some(f => f.value === fieldKey.value)) fieldKey.value = options[0]?.value || ''
})
function queueListSearch(key) {
  clearTimeout(searchTimer)
  if (!user.value) return
  pagers[key].page = 1
  requests[key] = (requests[key] || 0) + 1; listBusy[key] = false
  if (key === 'messages') selected.value = []
  if (page.value !== key || detail.value) return
  listBusy[key] = true
  searchTimer = setTimeout(async () => { if (!user.value || page.value !== key) return; try { await fetchPage(key) } catch (e) { error.value = e.message } }, 250)
}
watch([() => listQueries.messages, disposition], () => queueListSearch('messages'), { flush: 'sync' })
watch(() => listQueries.tickets, () => queueListSearch('tickets'), { flush: 'sync' })
watch(() => listQueries.qa, () => queueListSearch('qa'), { flush: 'sync' })
watch(() => [detail.value?.source_messages.length,bindings.value.length,form.claims?.length,form.answer_claims?.length,form.next_actions?.length,detail.value?.reviews.length,detail.value?.notes?.length], () => {
  const lists = { source: detail.value?.source_messages, evidence: bindings.value, claims: kind.value === 'ticket' ? form.claims : form.answer_claims, actions: form.next_actions, reviewHistory: detail.value?.reviews, notes: detail.value?.notes }
  for (const [key, items] of Object.entries(lists)) pagers[key].page = Math.min(pagers[key].page, Math.max(1, Math.ceil((items?.length || 0) / pageSize)))
})
onMounted(async () => { window.addEventListener('beforeunload', protectUnsaved); window.addEventListener('session-expired', sessionExpired); try { await loadCsrf(); user.value = await api('/auth/me'); await refresh() } catch (e) { if (e.status !== 401) error.value = e.message } finally { ready.value = true } timer = setInterval(() => { if (user.value && page.value === 'jobs') refreshJobs() }, 8000) })
onUnmounted(() => { clearInterval(timer); clearTimeout(searchTimer); clearTimeout(fileSearchTimer); window.removeEventListener('session-expired', sessionExpired); window.removeEventListener('beforeunload', protectUnsaved) })
</script>

<template>
  <div v-if="!ready" class="loading-screen"><RefreshCw class="spin"/>正在连接服务…</div>
  <div v-else-if="!user" class="login-page">
    <div class="login-story"><div class="brand"><span class="brand-icon"><MessagesSquare/></span>知序 <span class="brand-en">SERVICE RECORDS</span></div><div class="story-copy"><span class="eyebrow">每一次服务，都有迹可循</span><h1 tabindex="-1">让零散的对话，<br>成为有序的服务。</h1><p>从客户提问到解决方案，整理工单、沉淀知识。<br>保留每一条依据，让团队经验持续积累。</p><div class="story-line"><span>01 对话归档</span><ChevronRight/><span>02 服务跟进</span><ChevronRight/><span>03 知识沉淀</span></div></div><div class="story-bottom"><ShieldCheck size="16"/>内部使用 · 人工审核确认</div></div>
    <main class="login-form"><form @submit.prevent="signIn"><span class="eyebrow">欢迎回来</span><h2>登录系统</h2><p class="muted">使用管理员分配的内部账号登录</p><label>用户名<input v-model="loginForm.username" autocomplete="username" required placeholder="输入用户名"></label><label>密码<input v-model="loginForm.password" type="password" autocomplete="current-password" required placeholder="输入登录密码"></label><div v-if="error" class="alert error" role="alert">{{error}}</div><button class="primary wide" :disabled="loading">{{loading?'登录中…':'登录'}}<ChevronRight size="16"/></button><p class="login-foot">客户服务记录管理系统 · v0.1</p></form></main>
  </div>
  <div v-else class="shell" @click.capture="rememberDialogTrigger">
    <button v-if="isMobile && mobileNavOpen" class="mobile-nav-backdrop" type="button" tabindex="-1" aria-label="关闭导航遮罩" @click="closeMobileNav"/>
    <aside id="workspace-navigation" ref="navPanel" class="sidebar" :class="{'is-open':mobileNavOpen}" :inert="(isMobile && !mobileNavOpen) || !!appDialog" :aria-hidden="isMobile && !mobileNavOpen ? true : undefined" :role="isMobile ? 'dialog' : undefined" :aria-modal="isMobile && mobileNavOpen ? true : undefined" aria-label="工作区导航" @keydown="navKeydown"><div class="sidebar-heading"><a class="brand" @click="navigate('dashboard')"><span class="brand-icon"><MessagesSquare size="22"/></span>知序<span class="version">BETA</span></a><button ref="navClose" class="icon-button mobile-nav-close" type="button" aria-label="关闭导航" @click="closeMobileNav"><X size="22"/></button></div><div class="workspace-name">客户服务记录</div><nav aria-label="主要导航"><button v-for="n in primaryNav" :key="n.id" :class="{active:page===n.id}" :disabled="loading" @click="navigate(n.id)"><component :is="n.icon" size="19"/>{{n.label}}<span v-if="n.id==='reviews'&&overview.reviews" class="nav-count">{{overview.reviews}}</span></button></nav><details class="secondary-navigation" :open="toolsOpen" @toggle="toolsOpen=$event.target.open"><summary aria-label="工具与设置" title="工具与设置"><Settings size="18"/><span>工具与设置</span></summary><nav aria-label="工具导航"><button v-for="n in secondaryNav" :key="n.id" :class="{active:page===n.id}" :disabled="loading" @click="navigate(n.id)"><component :is="n.icon" size="18"/>{{n.label}}</button></nav></details><div class="sidebar-tip"><BookOpen size="19"/><p>好的知识，<br>从一次清晰的记录开始。</p></div><div class="user-card"><div class="avatar">{{user.display_name.slice(0,1)}}</div><div><strong>{{user.display_name}}</strong><small>{{roleNames[user.role]}}</small></div><button class="icon-button" @click="logout" title="退出登录" aria-label="退出登录"><LogOut size="17"/></button></div></aside>
    <div class="main-shell" :inert="backgroundBlocked"><header class="topbar"><div class="mobile-page-title"><button ref="navToggle" class="icon-button mobile-nav-toggle" type="button" aria-label="打开导航" :aria-expanded="mobileNavOpen" aria-controls="workspace-navigation" @click="toggleMobileNav"><Menu size="23"/></button><span>{{nav.find(n=>n.id===page)?.label}}</span></div><div class="topbar-actions"><button class="icon-button" @click="run(refresh)" :disabled="loading" title="刷新" aria-label="刷新"><RefreshCw size="17" :class="{spin:loading}"/></button></div></header>
    <main class="content"><div v-if="error" class="alert error" role="alert">{{error}}<button @click="error=''" class="icon-button"><X size="16"/></button></div><div v-if="success" class="alert success" role="status"><Check size="16"/>{{success}}<button v-if="lastDeleted" class="small" @click="undoDelete" :disabled="loading">撤销删除</button><button @click="success=''" class="icon-button"><X size="16"/></button></div>
      <template v-if="detail">
        <div class="page-heading"><div><button class="back" @click="closeDetail" :disabled="loading"><ArrowLeft size="15"/>{{detailReturnLabel}}</button><h1 tabindex="-1">{{kind==='ticket'?detail.object.ticket_no:detail.object.qa_no}}</h1><p>修改内容会创建新版本，正式内容在审核通过后更新</p></div><span class="badge" :class="currentRevision?.state">{{currentRevision?label(currentRevision.state):'尚无草稿'}}</span></div>
        <div class="editor-toolbar" role="region" aria-label="版本与草稿操作">
          <MoreActions v-if="isAdmin||canDeleteDraft(currentRevision)" :disabled="loading"><button v-if="isAdmin" class="danger" @click="askDelete(kind,detail.object)">删除记录</button><button v-if="canDeleteDraft(currentRevision)" class="danger" @click="askDelete(kind+'_draft',currentRevision)">删除此草稿</button></MoreActions>
          <select v-if="detail.revisions.length" :value="revisionId" @change="changeRevision" :disabled="loading" aria-label="记录版本"><option v-for="r in detail.revisions" :value="r.id">版本 {{r.revision_no}} · {{label(r.state)}} · {{r.origin==='ai'?'AI 生成':'人工编辑'}}{{r.id===detail.object.current_revision_id?' · 当前正式版本':''}}</option></select>
          <span v-if="currentRevision?.stale" class="warning-text">来源已变化，提交时会保存新草稿</span><div class="spacer"/>
          <button @click="saveDraft" :disabled="loading||(!editing&&!currentRevision?.stale&&!!currentRevision&&currentRevision.state!=='rejected')">保存草稿</button>
          <button v-if="canSubmitDraft" class="primary" @click="saveAndSubmit" :disabled="loading"><Check size="16"/>{{needsDraftSave?'保存并提交审核':'提交审核'}}</button>
        </div>
        <div class="mobile-editor-actions" role="region" aria-label="移动端草稿操作">
          <button @click="saveDraft" :disabled="loading||(!editing&&!currentRevision?.stale&&!!currentRevision&&currentRevision.state!=='rejected')">保存草稿</button>
          <button v-if="canSubmitDraft" class="primary" @click="saveAndSubmit" :disabled="loading"><Check size="16"/>{{needsDraftSave?'保存并提交审核':'提交审核'}}</button>
        </div>
        <fieldset class="editor-fields" :disabled="loading" :inert="loading"><div class="editor-grid"><section class="panel editor-form" @input="editing=true" @change="editing=true">
          <template v-if="kind==='ticket'">
            <h3>工单内容</h3>
            <p class="hint">工单至少关联一条有效原文，每条关键事实均须有证据；正文各字段无需重复关联。</p>
            <label>工单标题<input v-model="form.title"></label>
            <div class="field-heading"><label for="ticket-status">处理状态</label><button type="button" class="text-button evidence-shortcut" :class="evidenceState('status')" @click="requestEvidence('status')">{{evidenceText('status')}}</button></div>
            <select id="ticket-status" v-model="form.status" @change="markFieldChanged('status')"><option v-for="s in ['open','in_progress','waiting_customer','waiting_internal','answered','resolved','cancelled','unknown']" :value="s">{{label(s)}}</option></select>
            <div class="date-summary">
              <div><span>工单日期 · {{form.date_basis==='first_question'?'原始提问':'首次可见上下文'}}</span><strong>{{displayedTicketDate}}<small v-if="currentRevision&&!editing"> · 已保存版本</small></strong></div>
              <button v-if="displayedDateSource" type="button" class="text-button" @click="locateSource(displayedDateSource)">查看日期原文</button>
              <p class="hint">当前来源首次可见：{{date(firstVisibleMessage?.sent_at)}} · 保存时自动计算，无需选择</p>
              <p v-if="questionTimeUncertain" class="warning-text">部分提问缺少有效时间，无法自动确定最早提问，请人工核对日期依据。</p>
              <p v-if="dateNeedsReview" class="warning-text">{{!firstVisibleMessage?'来源缺少有效时间，请先核对来源时间。':form.date_basis==='first_visible_context'?'缺少原始提问，批准时仍需明确确认以首次可见上下文记录。':'原始提问来源待确认，请展开校正。'}}</p>
              <details :open="dateOptionsOpen" @toggle="dateOptionsOpen=$event.target.open">
                <summary>校正日期依据</summary>
                <label>日期依据<select v-model="form.date_basis" @change="changeDateBasis"><option value="first_question">原始提问日期</option><option value="first_visible_context">首次可见上下文日期</option></select></label>
                <label v-if="form.date_basis==='first_question'">原始提问消息<SearchSelect v-model="form.first_question_message_id" :options="questionDateOptions" aria-label="原始提问消息" placeholder="搜索原始提问的发送人、日期或原文" @change="editing=true;incompleteAccepted=false"/></label>
              </details>
            </div>
            <div class="field-heading"><label for="ticket-problem">问题内容</label><button type="button" class="text-button evidence-shortcut" :class="evidenceState('problem')" @click="requestEvidence('problem')">{{evidenceText('problem')}}</button></div>
            <textarea id="ticket-problem" v-model="form.problem" rows="4" placeholder="客户遇到了什么问题？" @input="markFieldChanged('problem')"></textarea>
            <label>影响范围<textarea v-model="form.impact" rows="2"></textarea></label>
            <div class="field-heading"><label for="ticket-handling">处理过程</label><button type="button" class="text-button evidence-shortcut" :class="evidenceState('handling_summary')" @click="requestEvidence('handling_summary')">{{evidenceText('handling_summary')}}</button></div>
            <textarea id="ticket-handling" v-model="form.handling_summary" rows="4" @input="markFieldChanged('handling_summary')"></textarea>
            <div class="field-heading"><label for="ticket-conclusion">当前结论</label><button type="button" class="text-button evidence-shortcut" :class="evidenceState('current_conclusion')" @click="requestEvidence('current_conclusion')">{{evidenceText('current_conclusion')}}</button></div>
            <textarea id="ticket-conclusion" v-model="form.current_conclusion" rows="3" placeholder="记录有证据支持的结论" @input="markFieldChanged('current_conclusion')"></textarea>
          </template>
          <template v-else>
            <h3>知识内容</h3>
            <div class="field-heading"><label for="qa-question">问题</label><button type="button" class="text-button evidence-shortcut" :class="evidenceState('question')" @click="requestEvidence('question')">{{evidenceText('question')}}</button></div>
            <textarea id="qa-question" v-model="form.question" rows="3" @input="markFieldChanged('question')"></textarea>
            <label>答案状态<select v-model="form.answer_state"><option v-for="s in ['supported','no_answer','conflict','missing_context']" :value="s">{{label(s)}}</option></select></label>
            <div class="field-heading"><label for="qa-answer">回答</label><button type="button" class="text-button evidence-shortcut" :class="evidenceState('answer')" @click="requestEvidence('answer')">{{evidenceText('answer')}}</button></div>
            <textarea id="qa-answer" v-model="form.answer" rows="7" placeholder="填写已被原文证实的回答，保留适用条件" @input="markFieldChanged('answer')"></textarea>
            <label>适用条件<textarea v-model="form.applicability" rows="3"></textarea></label>
          </template>
          <details class="editor-disclosure" :open="claimsOpen" @toggle="claimsOpen=$event.target.open">
            <summary>关键事实与依据 <span class="muted">{{editorClaims.length}} 项</span><span v-if="claimProblems" class="warning-text"> · {{claimProblems}} 项待核对</span><span v-else-if="kind==='qa'&&!editorClaims.length" class="warning-text"> · 尚未列出关键事实</span><span v-else-if="editorClaims.length" class="muted"> · 均已关联支持依据</span></summary>
            <p class="hint">已有事实和原文关联可直接核对。内容有变更时请同步检查依据，无需重复录入已有事实。</p>
            <div class="section-line"><span class="muted">每项事实可直接定位原文</span><button type="button" class="small" @click="addClaim"><Plus size="14"/>添加事实</button></div>
            <div v-for="(c,i) in localItems(editorClaims,'claims')" :key="c.claim_key" class="fact-card">
              <div class="field-heading"><label :for="'claim-'+c.claim_key">事实 {{(pagers.claims.page-1)*pageSize+i+1}}</label><button type="button" class="text-button evidence-shortcut" :class="evidenceState(claimPrefix+c.claim_key)" @click="requestEvidence(claimPrefix+c.claim_key)">{{evidenceText(claimPrefix+c.claim_key)}}</button><button type="button" class="icon-button" :aria-label="'移除事实 '+((pagers.claims.page-1)*pageSize+i+1)" @click="removeClaim(c)"><X size="15"/></button></div>
              <textarea :id="'claim-'+c.claim_key" v-model="c.text" rows="2" placeholder="一个可由原文证明的事实" @input="markFieldChanged(claimPrefix+c.claim_key)"></textarea>
            </div>
            <Pagination v-if="editorClaims.length>pageSize" :page="pagers.claims.page" :total="editorClaims.length" :disabled="loading" @change="n=>pagers.claims.page=n"/>
          </details>
          <template v-if="kind==='ticket'"><div class="section-line"><h3>待办事项</h3><button class="small" @click="form.next_actions.push({text:'',basis:'reviewer_suggestion',evidence_span_ids:[]});editing=true"><Plus size="14"/>添加待办</button></div><div v-for="(a,i) in localItems(form.next_actions,'actions')" class="next-action"><input v-model="a.text" placeholder="下一步安排"><select v-model="a.basis"><option value="reviewer_suggestion">审核员建议</option><option value="explicit_in_chat">聊天明确提及</option></select><select v-if="a.basis==='explicit_in_chat'" multiple v-model="a.evidence_span_ids"><option v-for="b in bindings" :value="b.evidence_span_id">{{b.excerpt?.slice(0,45)}}</option></select><button class="small" @click="form.next_actions.splice((pagers.actions.page-1)*pageSize+i,1);editing=true">移除</button></div><Pagination v-if="form.next_actions.length>pageSize" :page="pagers.actions.page" :total="form.next_actions.length" :disabled="loading" @change="n=>pagers.actions.page=n"/></template>
          <ContributorPicker v-else :model-value="form.contributors" :bindings="bindings" :messages="detail.source_messages" :participants="people" :disabled="loading" @update:model-value="updateContributors" @locate="locateSource"/>
          <details class="editor-disclosure" :open="bindingsOpen" @toggle="bindingsOpen=$event.target.open">
            <summary>全部原文依据 <span class="muted">{{bindings.length}} 条</span><span v-if="evidenceProblems" class="warning-text"> · {{evidenceProblems}} 条待处理</span></summary>
            <p class="hint">可从内容旁直接查看依据；需要调整关联关系或移除时，在这里操作。</p>
            <div v-for="(b,i) in localItems(bindings,'evidence')" :key="b.field_key+':'+b.evidence_span_id" class="evidence-item">
              <div><span class="evidence-field-label">{{evidenceFieldLabel(b.field_key)}}</span><select v-model="b.relation" :aria-label="evidenceFieldLabel(b.field_key)+'的证据关系'"><option value="supports">支持</option><option value="context">上下文</option><option value="contradicts">矛盾</option></select><button type="button" class="icon-button" :aria-label="'移除'+evidenceFieldLabel(b.field_key)+'的依据'" @click="bindings.splice((pagers.evidence.page-1)*pageSize+i,1);editing=true"><X size="14"/></button></div>
              <p>{{b.excerpt}}</p><p v-if="!detail.source_messages.some(m=>m.id===b.message_id&&!m.is_deleted)" class="warning-text">来源已删除或不再关联本记录，历史摘录已保留；保存新稿前请更换或移除此关联。</p><button type="button" class="text-button" @click="fieldKey=b.field_key;locateSource(b)">定位原文</button>
            </div>
            <p v-if="!bindings.length" class="hint">尚无依据，可从内容旁点击“补充原文依据”。</p>
            <Pagination v-if="bindings.length>pageSize" :page="pagers.evidence.page" :total="bindings.length" :disabled="loading" @change="n=>pagers.evidence.page=n"/>
          </details>
        </section>
        <aside class="source-panel"><EvidencePicker :key="detail.object.id+':'+revisionId" :messages="detail.source_messages" :fields="fieldOptions" v-model:field-key="fieldKey" :busy="loading" :focus-request="evidenceFocus" :selection-request="evidenceSelection" @add="addEvidence"/></aside>
        </div>
        <section class="panel review-panel"><div><h3>审核与处理记录</h3><p class="hint">当前正式版本：{{detail.object.current_revision_id?'已发布版本 '+detail.revisions.find(r=>r.id===detail.object.current_revision_id)?.revision_no:'尚未批准'}}<span v-if="hasUnsavedInput" class="warning-text"> · 有未保存正文或未提交意见</span></p></div><label for="review-comment">审核意见 / 内部备注</label><textarea id="review-comment" v-model="comment" rows="2" placeholder="填写审核意见、驳回原因或内部备注"></textarea><p class="hint review-comment-hint">意见按当前记录和版本临时保留，切换版本可恢复。提交审核、批准、驳回或保存备注后才会记录到系统；关闭或刷新页面前会提醒未提交的输入。</p><label v-if="kind==='ticket'&&form.date_basis==='first_visible_context'" class="checkbox-label"><input type="checkbox" v-model="incompleteAccepted">确认缺少原始提问，按首次可见上下文记录</label><div class="actions"><button v-if="kind==='ticket'" @click="addNote" :disabled="loading">保存内部备注</button><template v-if="canReview&&currentRevision?.state==='in_review'"><button class="danger" @click="review('reject')" :disabled="loading||editing">驳回</button><button class="primary" @click="review('approve')" :disabled="loading||editing"><Check size="16"/>批准此版本</button></template></div><ReviewHistory :reviews="localItems(detail.reviews,'reviewHistory')" :busy="loading" @open-revision="selectRevision"/><Pagination v-if="detail.reviews.length>pageSize" :page="pagers.reviewHistory.page" :total="detail.reviews.length" :disabled="loading||listBusy.reviewHistory" @change="n=>pagers.reviewHistory.page=n"/><div v-for="n in localItems(detail.notes,'notes')" :key="n.id" class="history-row"><span class="badge">内部备注</span><span>{{n.body}}</span><small>{{n.author_name||n.author_username||'未知账号'}} · {{date(n.created_at)}}</small></div><Pagination v-if="(detail.notes||[]).length>pageSize" :page="pagers.notes.page" :total="(detail.notes||[]).length" :disabled="loading||listBusy.notes" @change="n=>pagers.notes.page=n"/></section></fieldset>
      </template>
      <template v-else-if="page==='dashboard'"><div class="page-heading"><div><span class="eyebrow">服务概览</span><h1 tabindex="-1">把每一次沟通，整理清楚。</h1><p>记录问题、追踪处理，让经验成为团队的知识。</p></div><button class="primary" @click="openFileLibrary"><Plus size="17"/>导入聊天记录</button></div><DashboardMetrics :overview="overview" :disabled="loading" @navigate="navigateMetric"/><div class="dashboard-grid"><section class="panel"><div class="section-line"><h3>最近的服务记录</h3><button class="text-button" @click="navigate('tickets')">查看全部<ChevronRight size="14"/></button></div><div class="record-row" v-for="t in recentTickets" @click="run(()=>openObject('ticket',t.id,true))"><span class="record-icon"><Tickets size="18"/></span><div><strong>{{t.latest_revision?.title||issues.find(i=>i.id===t.issue_id)?.label||'待编辑工单'}}</strong><small>{{t.ticket_no}}</small></div><span class="badge" :class="t.latest_revision?.state">{{label(t.latest_revision?.state||'draft')}}</span></div><div v-if="!recentTickets.length" class="empty"><MessagesSquare size="38"/><h3>从一份聊天记录开始</h3><p>直接导入纯文本聊天记录，开始整理工单和 QA。</p><button @click="openFileLibrary">导入聊天记录<ChevronRight size="15"/></button></div></section><section class="panel workflow-card"><span class="eyebrow">工作流程</span><h3>从对话到知识</h3><div v-for="(s,i) in [['导入聊天','上传文本，自动识别客服与客户'],['归属问题','同一个问题，跨天持续跟进'],['编辑与审核','每条关键结论都有原文依据'],['沉淀知识','审核通过后成为正式 QA']]" class="workflow-step"><span>{{i+1}}</span><div><strong>{{s[0]}}</strong><small>{{s[1]}}</small></div></div><p class="hint"><ShieldCheck size="14"/>AI 结果先进入草稿，由人工审核确认。</p></section></div></template>
      <template v-else-if="page==='messages'">
        <button v-if="currentFile" class="back" @click="backToFiles" :disabled="loading"><ArrowLeft size="15"/>返回文件列表</button>
        <div class="page-heading file-detail-heading"><div><h1 tabindex="-1">{{currentFile?currentFile.original_filename:'聊天记录'}}</h1><p>{{currentFile?'在本文件生成并核对草稿，也可查看聊天原文、筛选消息和整理归属。':'按导入文件管理聊天记录，先查找文件，再查看文件内的消息。'}}</p></div></div>
        <template v-if="!currentFile">
          <div class="panel upload-panel"><div class="upload-icon"><Upload/></div><div><h3>导入纯文本聊天记录</h3><p>支持 TXT、Markdown · 最大 10MB · 导入前可预览确认</p></div><div class="spacer"/><input type="file" accept=".txt,.md,.log,text/plain" @change="uploadFile=$event.target.files[0]" aria-label="选择聊天记录文件"><button class="primary" @click="upload" :disabled="loading||!canImport"><Upload size="16"/>上传并预览</button></div>
          <section class="panel import-files-panel">
            <div class="section-line"><h3><FileText size="18"/>导入文件</h3><span class="muted">{{pagers.imports.total}} 个文件</span></div>
            <div class="table-toolbar file-library-toolbar">
              <div class="search"><Search size="16"/><input v-model="fileQuery" :disabled="loading" placeholder="输入文件名搜索" maxlength="200" aria-label="搜索导入文件"></div>
              <MoreActions class="list-filters" :label="activeFilterCount?`筛选（${activeFilterCount}）`:'筛选'" :disabled="loading"><div class="list-filter-fields">
                <label>导入状态<select v-model="fileStatus" aria-label="文件导入状态" :disabled="loading"><option value="all">全部导入状态</option><option value="confirmed">已确认导入</option><option value="pending">待确认导入</option></select></label>
                <label v-if="isAdmin">记录范围<select v-model="trash.imports" @change="run(()=>changeTrash('imports'))" aria-label="导入文件范围" :disabled="loading"><option :value="false">正常文件</option><option :value="true">已删除文件</option></select></label>
              </div></MoreActions>
              <span v-if="activeFilterCount" class="filter-summary">{{[fileStatus!=='all'?(fileStatus==='confirmed'?'已确认导入':'待确认导入'):'',trash.imports?'已删除文件':''].filter(Boolean).join(' · ')}}</span>
              <button v-if="activeFilterCount||fileQuery" class="text-button" @click="clearFilters" :disabled="loading">清除筛选</button>
            </div>
            <article v-for="b in imports" :key="b.id" class="import-file-row">
              <div class="import-file-icon"><FileText size="22"/></div>
              <div class="import-file-info">
                <button class="import-file-name text-button" @click="b.confirmed_at?openChatFile(b):run(()=>openPreview(b.id))" :disabled="loading">{{b.original_filename}}</button>
                <small>导入于 {{date(b.created_at)}} · 原始 {{b.message_count}} 条</small>
                <div class="import-file-summary"><span class="badge" :class="b.is_deleted?'ignored':b.confirmed_at?'succeeded':'pending'">{{b.is_deleted?'已删除':b.confirmed_at?'已确认导入':'待确认导入'}}</span><span v-if="b.confirmed_at">{{b.is_deleted?'已删除 '+(b.message_counts?.deleted??0)+' 条':'可查看 '+(b.message_counts?.active??0)+' 条 · 待归属 '+(b.message_counts?.pending??0)+' 条'}}</span><span v-if="!b.is_deleted&&b.message_counts?.deleted">已删除 {{b.message_counts.deleted}} 条</span></div>
                <small v-if="b.screening_summary">预筛选：保留 {{b.screening_summary.retained}} 条 · 过滤 {{b.screening_summary.filtered}} 条 · 已恢复 {{b.screening_summary.restored}} 条</small>
              </div>
              <div class="import-file-actions">
                <button v-if="b.confirmed_at" class="primary small" @click="openChatFile(b)" :disabled="loading">{{b.is_deleted?'查看已删除聊天':'打开文件'}}<ChevronRight size="14"/></button>
                <button class="small" @click="run(()=>openPreview(b.id))" :disabled="loading">{{b.confirmed_at?'查看导入结果':'查看预览'}}</button>
                <MoreActions v-if="isAdmin&&!b.is_deleted" :disabled="loading"><button class="danger" @click="askDelete('import',b)">删除文件记录</button></MoreActions>
                <button v-if="isAdmin&&b.is_deleted" class="small" @click="restoreRecord('import',b)" :disabled="loading">恢复文件</button>
              </div>
            </article>
            <div v-if="!imports.length" class="empty"><FileText size="34"/><p>暂无符合条件的文件</p><small>可调整搜索条件，或上传聊天记录。</small></div>
            <Pagination :page="pagers.imports.page" :total="pagers.imports.total" :disabled="loading||listBusy.imports" @change="n=>goPage('imports',n)"/>
          </section>
        </template>
        <template v-else>
          <section class="panel current-file-panel">
            <div><h3><FileText size="18"/>当前文件</h3><p class="hint">导入于 {{date(currentFile.created_at)}} · 原始 {{currentFile.message_count}} 条 · 可查看 {{currentFile.message_counts?.active??0}} 条 · 已删除 {{currentFile.message_counts?.deleted??0}} 条</p><span v-if="currentFile.is_deleted" class="warning-text">文件已删除，当前仅供管理员查看历史消息。</span></div>
            <div class="current-file-actions"><button class="small" @click="run(()=>openPreview(currentFile.id))" :disabled="loading">查看导入结果 / 恢复消息</button><button v-if="isAdmin&&currentFile.is_deleted" class="small" @click="restoreRecord('import',currentFile)" :disabled="loading">恢复文件</button></div>
          </section>
          <FileProcessing :key="currentFile.id" :batch="currentFile" :profiles="profiles" v-model:profile="modelProfile" v-model:mode="extractMode" :can-generate="canImport" :busy="loading" :latest-job="latestFileJob" @generate="extract(currentFile.id,null)" @open-record="openJobRecord" @changed="fileProcessingChanged"/>
          <div v-if="lastAssignment" class="assignment-destination"><span>已归属：{{lastAssignment.label}}</span><button class="text-button" :disabled="loading" @click="openAssignedIssue(lastAssignment)">打开所属工单<ChevronRight :size="14"/></button></div><div class="panel"><div class="table-toolbar"><div class="search"><Search size="16"/><input v-model="query" :disabled="loading" placeholder="在此文件中搜索消息或发送人" maxlength="200"></div><MoreActions class="list-filters" :label="activeFilterCount?`筛选（${activeFilterCount}）`:'筛选'" :disabled="loading"><div class="list-filter-fields"><label>归属状态<select v-model="disposition" aria-label="消息归属状态" :disabled="loading"><option value="">全部处置状态</option><option v-for="s in ['pending','needs_review','assigned','ignored']" :value="s">{{label(s)}}</option></select></label><label v-if="isAdmin">记录范围<select v-model="trash.messages" @change="run(()=>changeTrash('messages'))" aria-label="聊天记录范围" :disabled="loading"><option :value="false">正常记录</option><option :value="true">已删除</option></select></label></div></MoreActions><span v-if="activeFilterCount" class="filter-summary">{{[disposition?label(disposition):'',trash.messages?'已删除消息':''].filter(Boolean).join(' · ')}}</span><button v-if="activeFilterCount||query" class="text-button" @click="clearFilters" :disabled="loading">清除筛选</button><span class="muted">{{totalMessages}} 条消息</span></div><div class="message-table"><div class="message-head"><input v-if="canImport&&!trash.messages" type="checkbox" aria-label="选择本页消息" :checked="!!visibleMessages.length&&selected.length===visibleMessages.length" :indeterminate="selected.length>0&&selected.length<visibleMessages.length" :disabled="loading||listBusy.messages||!visibleMessages.length" @change="selected=$event.target.checked?visibleMessages.filter(m=>!m.is_deleted).map(m=>m.id):[]"><span v-else></span><span>发送人 / 时间</span><span>聊天原文</span><span>归属状态</span></div><article v-for="m in visibleMessages" :key="m.id" class="message-row"><input type="checkbox" :value="m.id" v-model="selected" :aria-label="`选择 ${m.sender_name_raw} 的消息`" :disabled="loading||listBusy.messages||trash.messages||!canImport"><div class="message-author"><strong>{{m.sender_name_raw||'未知成员'}}</strong><small>{{date(m.sent_at)}}</small><small class="source-filename">{{m.source_filename}}</small><span class="sender-role">{{m.sender_role==='support'?'客服':'客户'}}</span></div><pre>{{m.raw_text}}</pre><div class="disposition-cell"><span class="badge" :class="m.disposition">{{label(m.disposition)}}</span><div v-if="m.assigned_issues?.length" class="message-issue-links"><button v-for="issue in m.assigned_issues" :key="issue.issue_id" type="button" class="text-button" :disabled="loading" @click="openAssignedIssue(issue)">{{issue.label}}<ChevronRight :size="12"/></button></div><small v-if="dispositionReason(m)" :class="{'warning-text':m.disposition_reason==='nontext_only'&&m.kind==='text'}">{{dispositionSource(m)}} · {{dispositionReason(m)}}</small><div v-if="isAdmin" class="record-actions"><MoreActions v-if="!m.is_deleted" :disabled="loading||listBusy.messages"><button class="danger" @click="askDelete('message',m)">删除</button></MoreActions><button v-else-if="!m.deleted_with_import" class="small" @click="restoreRecord('message',m)" :disabled="loading">恢复</button><small v-else>从文件列表恢复所属文件</small></div></div></article><div v-if="!visibleMessages.length" class="empty"><FileText size="34"/><p>暂无符合条件的消息</p></div></div><Pagination :page="pagers.messages.page" :total="pagers.messages.total" :disabled="loading||listBusy.messages" @change="n=>goPage('messages',n)"/></div>
          <section v-if="canImport&&selected.length&&!trash.messages" class="panel assignment-bar"><div class="selection-summary"><strong>已选 {{selected.length}} 条</strong><button class="text-button" @click="selected=[]" :disabled="loading">取消选择</button></div><fieldset class="assignment-fields" :disabled="loading||listBusy.messages" :inert="loading||listBusy.messages"><div class="assignment-primary"><SearchSelect v-model="messageAssignIssue" :options="assignmentOptions" aria-label="聊天归属问题" placeholder="输入关键词搜索已有问题，或建立新问题"/><input v-if="messageAssignIssue==='__new__'" v-model="assignTitle" placeholder="新问题标题"><select v-model="assignRelation" aria-label="所选消息与问题的关系"><option value="question">提问</option><option value="answer">回答</option><option value="progress">跟进</option><option value="correction">纠正</option><option value="context">上下文</option></select><button class="primary" @click="assign" :disabled="loading||!messageAssignIssue||(messageAssignIssue==='__new__'&&!assignTitle.trim())">确认归属</button></div><details class="assignment-more"><summary>更多处置</summary><div><button @click="recheckSelected" :disabled="loading||listBusy.messages">转为待核对</button><label>忽略原因<input v-model="ignoreReason" placeholder="填写忽略原因"></label><button @click="ignoreSelected" :disabled="loading||listBusy.messages||!ignoreReason.trim()">忽略所选</button></div></details></fieldset></section>
        </template>
      </template>
      <template v-else-if="page==='tickets'||page==='qa'"><div class="page-heading"><div><h1 tabindex="-1">{{page==='tickets'?'服务工单':'知识 QA'}}</h1><p>{{page==='tickets'?'一个问题一张工单，跨天追加处理记录。':'从服务记录提炼可复用的问答，审核后进入正式知识。'}}</p></div><button v-if="page==='tickets'" class="primary" @click="openFileLibrary"><Plus size="16"/>从聊天创建工单</button><button v-else @click="qaCreateOpen=!qaCreateOpen" :aria-expanded="qaCreateOpen" :disabled="loading"><Plus size="16"/>手动新建 QA</button></div><div v-if="page==='qa'&&qaCreateOpen" class="panel inline-create"><SearchSelect v-model="qaSource" :options="activeIssueOptions" aria-label="QA 来源问题" placeholder="输入关键词搜索来源问题"/><button class="primary" @click="createQA" :disabled="loading||!qaSource"><Plus size="16"/>新建 QA 草稿</button></div><div class="panel"><div class="table-toolbar"><div class="search"><Search size="16"/><input v-model="query" :disabled="loading" placeholder="搜索标题或内容" maxlength="200"></div><MoreActions v-if="isAdmin" class="list-filters" :label="activeFilterCount?`筛选（${activeFilterCount}）`:'筛选'" :disabled="loading"><div class="list-filter-fields"><label>记录范围<select v-model="trash[page]" @change="run(()=>changeTrash(page))" aria-label="工单或QA记录范围" :disabled="loading"><option :value="false">正常记录</option><option :value="true">已删除</option></select></label></div></MoreActions><span v-if="trash[page]" class="filter-summary">已删除记录</span><button v-if="activeFilterCount||query" class="text-button" @click="clearFilters" :disabled="loading">清除筛选</button><span class="muted">{{pagers[page].total}} 条记录</span></div><div class="object-table"><div class="object-head"><span>{{page==='tickets'?'工单标题':'问题'}}</span><span>来源文件</span><span>审核状态</span><span>更新日期</span><span></span></div><article v-for="o in filteredObjects" class="object-row" @click="!o.is_deleted&&run(()=>openObject(page==='tickets'?'ticket':'qa',o.id))"><div><strong>{{page==='tickets'?(o.latest_revision?.title||issues.find(i=>i.id===o.issue_id)?.label||'待编辑工单'):(o.latest_revision?.question||'待编辑知识')}}</strong><small>{{o.ticket_no||o.qa_no}} <span v-if="o.current_revision_id" class="approved-dot">· 已有正式版本</span></small></div><span class="source-filename" :title="sourceNames(o)">{{sourceNames(o)}}</span><span class="badge" :class="o.latest_revision?.state">{{label(o.latest_revision?.state||'draft')}}</span><span class="muted">{{date(o.updated_at)}}</span><div class="record-actions"><button v-if="o.is_deleted&&isAdmin" class="small" @click.stop="restoreObject(page==='tickets'?'ticket':'qa',o)" :disabled="loading">恢复</button><MoreActions v-else-if="isAdmin||canDeleteDraft(o.latest_revision)" :disabled="loading||listBusy[page]"><button v-if="isAdmin" class="danger" @click="askDelete(page==='tickets'?'ticket':'qa',o)">删除</button><button v-else class="danger" @click="askDelete((page==='tickets'?'ticket':'qa')+'_draft',o.latest_revision)">删除草稿</button></MoreActions><ChevronRight v-if="!o.is_deleted" size="16"/></div></article><div v-if="!filteredObjects.length" class="empty"><component :is="page==='tickets'?Tickets:BookOpen" size="36"/><h3>尚无{{page==='tickets'?'工单':'知识记录'}}</h3><p>{{page==='tickets'?'为聊天消息归属问题后，即可编辑服务工单。':'选择来源问题，创建第一条 QA 草稿。'}}</p></div></div><Pagination :page="pagers[page].page" :total="pagers[page].total" :disabled="loading||listBusy[page]" @change="n=>goPage(page,n)"/></div></template>
      <template v-else-if="page==='reviews'"><div class="page-heading"><div><h1 tabindex="-1">审核中心</h1><p>核对内容、贡献者与原文证据，再确认正式版本。</p></div><span class="badge in_review">{{pagers.reviews.total}} 条待审核</span></div><div class="panel"><div v-for="o in pendingReviews" class="review-row"><span class="record-icon"><component :is="o.objectKind==='ticket'?Tickets:BookOpen" size="19"/></span><div><strong>{{o.latest_revision.title||o.latest_revision.question}}</strong><small>{{o.objectKind==='ticket'?'服务工单':'知识 QA'}} · {{o.ticket_no||o.qa_no}} · 版本 {{o.latest_revision.revision_no}}</small></div><span v-if="o.latest_revision.stale" class="warning-text">来源已变化</span><button @click="run(()=>openObject(o.objectKind,o.id,true))">查看与审核<ChevronRight size="15"/></button></div><div v-if="!pendingReviews.length" class="empty"><ClipboardCheck size="38"/><h3>当前没有待审核记录</h3><p>草稿提交后会出现在这里。</p></div><Pagination :page="pagers.reviews.page" :total="pagers.reviews.total" :disabled="loading||listBusy.reviews" @change="n=>goPage('reviews',n)"/></div></template>
      <template v-else-if="page==='jobs'"><div class="page-heading"><div><h1 tabindex="-1">AI 任务</h1><p>问题归属与内容抽取分别运行，结果进入人工草稿。</p></div></div><RefreshStatus :error="jobRefresh.error" :last-success="jobRefresh.lastSuccess" :busy="loading||listBusy.jobs" @retry="refreshJobs"/><details class="panel advanced-generation"><summary>对已有问题重新生成</summary><p class="hint">日常导入和生成可在聊天文件内完成；需要重新抽取某个已有问题时再展开配置。</p><div class="model-config"><label>模型配置<select v-model="modelProfile"><option v-for="p in profiles" :value="p.id">{{p.id==='local'?'本地 / 内网':'外部模型'}} · {{p.configured?'已配置':'未配置'}}</option></select></label><label>生成内容<select v-model="extractMode"><option value="both">工单与 QA</option><option value="ticket">仅工单</option><option value="qa">仅 QA</option></select></label><div class="spacer"/><p class="hint">可从文件列表运行完整流程，或对已有问题重新抽取。</p></div><div class="inline-create"><SearchSelect v-model="assignIssue" :options="issueOptions" aria-label="AI 抽取问题" placeholder="输入关键词搜索已有问题重新抽取"/><button class="primary" @click="extract(null,assignIssue)" :disabled="!assignIssue||!profiles.find(p=>p.id===modelProfile)?.configured||loading"><Sparkles size="16"/>生成草稿</button></div></details><div v-if="!profiles.some(p=>p.configured)" class="alert">Dify 服务接入地址已配置。请在部署环境填写两条已发布 Workflow 的 API Key，重建 API 和 Worker 容器后即可启用。</div><section class="panel"><div v-for="j in jobs" class="job-row"><div><strong>{{j.batch_id?'聊天归属 + 内容抽取':'问题内容抽取'}}</strong><small>{{j.id.slice(0,8)}} · {{date(j.created_at)}} · {{j.model_profile_snapshot.id==='local'?'本地':'外部'}}模型</small><small v-if="j.checkpoint?.messages_total">已处理消息 {{j.checkpoint.messages_done||0}} / {{j.checkpoint.messages_total}} · 归属批次 {{j.checkpoint.topic_batches||0}} · 草稿问题 {{j.checkpoint.extraction_done||0}} / {{j.checkpoint.extraction_total||0}}</small><small v-if="j.state==='running' && j.checkpoint?.map_parts_total">长问题分段 {{j.checkpoint.map_parts_done||0}} / {{j.checkpoint.map_parts_total}}</small><small v-if="j.checkpoint?.needs_review_messages">任务结束时待人工归属 {{j.checkpoint.needs_review_messages}} 条</small><p v-if="j.error_summary" class="warning-text">{{j.error_summary}}</p></div><span class="badge" :class="j.state">{{label(j.state)}}</span><button v-if="['succeeded','partial_failed'].includes(j.state)" @click="run(()=>showJobRecords(j))" :disabled="loading">查看生成记录</button><button v-if="['failed','partial_failed','cancelled'].includes(j.state)" @click="jobAction(j,'retry')" :disabled="loading">从断点继续</button><button v-if="['queued','running'].includes(j.state)" @click="jobAction(j,'cancel')" :disabled="loading">取消</button></div><div v-if="!jobs.length" class="empty"><Sparkles size="36"/><p>暂无 AI 任务</p></div><Pagination :page="pagers.jobs.page" :total="pagers.jobs.total" :disabled="loading||listBusy.jobs" @change="n=>goPage('jobs',n)"/></section></template>
      <template v-else-if="page==='settings'">
        <div class="page-heading"><div><h1 tabindex="-1">系统设置</h1><p>管理内部账号、姓名与角色。</p></div></div>
        <UserManagement v-if="user.role==='admin'" :current-user="user" :reload-token="userManagementReload" @self-updated="value=>user={...user,...value}" @reauthenticate="accountReauthenticate"/>
        <section v-else class="panel"><h3>当前账号</h3><p>{{user.display_name}} · {{roleNames[user.role]}}</p><p class="hint">内部账号由管理员维护。</p></section>
      </template>
    </main><footer>知序 · 客户服务记录<span>保留依据，积累经验</span></footer></div>
    <div v-if="deletion" class="modal-backdrop" @click.self="closeAppDialog" @keydown="dialogKeydown"><section class="modal delete-modal" data-app-dialog="delete" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="delete-title"><h2 id="delete-title">确认删除</h2><p class="delete-label">{{deletion.title}}</p><p class="hint">删除后将从正常列表移除，可恢复。聊天原文、已批准版本及历史证据会保留。</p><div class="actions"><button @click="deletion=null" :disabled="loading">取消</button><button class="danger" @click="deleteConfirmed" :disabled="loading">确认删除</button></div></section></div>
    <div v-if="jobResults" class="modal-backdrop" @click.self="closeAppDialog" @keydown="dialogKeydown"><section class="modal" data-app-dialog="results" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="job-records-title"><div class="section-line"><div><h2 id="job-records-title">任务生成记录</h2><p class="muted">任务 {{jobResults.id.slice(0,8)}} · {{label(jobResults.state)}} · 共 {{pagers.jobRecords.total}} 条</p></div><button @click="jobResults=null">关闭</button></div><div v-for="r in generatedRecords" :key="r.record_kind+r.revision_id" class="result-row"><div><strong>{{r.title}}</strong><small>{{r.record_kind==='ticket'?'工单':'QA'}} · {{r.record_no}} · 版本 {{r.revision_no}} · {{({created:'新增草稿',updated:'更新草稿',reused:'复用已有版本',manual_review_required:'已有人工草稿或待审核内容，未覆盖'})[r.action]}}</small></div><span class="badge">{{r.is_deleted?'已删除':label(r.state)}}</span><button @click="openJobRecord(r)" :disabled="loading||r.is_deleted">查看此版本</button></div><p v-if="!generatedRecords.length" class="hint">本次任务未生成工单或 QA，可查看任务处理情况。</p><Pagination :page="pagers.jobRecords.page" :total="pagers.jobRecords.total" :disabled="loading" @change="n=>run(()=>showJobRecords(jobResults,n))"/></section></div>
    <div v-if="preview" class="modal-backdrop" @click.self="closeAppDialog" @keydown="dialogKeydown"><section class="modal import-preview-modal" data-app-dialog="preview" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="import-preview-title">
      <div class="section-line"><div><h2 id="import-preview-title">{{preview.batch.confirmed_at?'导入结果':'导入预览'}}</h2><p class="muted">{{preview.batch.original_filename}} · 共 {{screeningSummary?.total ?? preview.batch.message_count ?? preview.total}} 条 · {{preview.batch.source_encoding}}</p></div><button @click="preview=null" class="icon-button" :disabled="loading" aria-label="关闭导入预览"><X/></button></div>
      <div v-if="error" class="alert error" role="alert">{{error}}</div>
      <div v-if="previewNotice" class="alert success" role="status">{{previewNotice}}</div>
      <section v-if="screeningSummary" class="screening-summary" aria-label="预筛选结果">
        <h3>预筛选结果</h3><p class="hint">仅排除确定噪声，聊天原文完整保留。保留消息中包含已恢复的消息。</p>
        <div class="screening-counts"><div><span>总数</span><strong>{{screeningSummary.total}}<small>条</small></strong></div><div><span>保留</span><strong>{{screeningSummary.retained}}<small>条</small></strong></div><div><span>过滤</span><strong>{{screeningSummary.filtered}}<small>条</small></strong></div><div><span>已恢复</span><strong>{{screeningSummary.restored}}<small>条</small></strong></div></div>
        <p v-if="screeningSummary.reasons?.length" class="screening-reasons">过滤原因：{{screeningReasons(screeningSummary)}}</p><p v-else class="screening-reasons">没有需要过滤的确定噪声。</p>
      </section>
      <p v-else class="alert">未执行本次预筛选，以下保留原导入记录。</p>
      <ImportWarnings :key="preview.batch.id" :warnings="preview.warnings" :busy="loading" :focused-index="previewFocusIndex" @locate="locatePreviewWarning"/>
      <div v-if="screeningSummary" class="screening-toolbar"><div class="screening-filters" role="group" aria-label="查看筛选结果"><button v-for="option in [{value:'all',label:'全部'},{value:'filtered',label:'已过滤'},{value:'retained',label:'保留'}]" :key="option.value" class="small" :class="{active:previewScreening===option.value}" :aria-pressed="previewScreening===option.value" :disabled="loading" @click="changePreviewScreening(option.value)">{{option.label}}</button></div><span class="muted">当前 {{preview.total}} 条 · 以下为聊天原文</span></div>
      <div class="preview-list"><article v-for="(m,i) in preview.records" :key="m.message_id || `${preview.page}-${i}`" :id="`preview-source-${m.source_index}`" :class="{'preview-warning-focus':previewFocusIndex===m.source_index}" tabindex="-1"><span class="muted">{{m.source_index+1}}</span><div class="preview-message"><div class="preview-message-heading"><strong>{{m.sender||'待确认'}} · {{date(m.sent_at)}}</strong><span v-if="m.is_deleted" class="badge ignored">已删除</span><span v-else-if="m.prefilter_restored" class="badge approved">已恢复</span><span v-else-if="m.prefilter_filtered" class="badge ignored">已过滤</span><span v-else-if="screeningSummary" class="badge pending">保留</span></div><p v-if="m.prefilter_reason_label" class="screening-message-reason">{{m.prefilter_restored?'原过滤原因':'过滤原因'}}：{{m.prefilter_reason_label}}</p><p v-if="previewFocusIndex===m.source_index" class="preview-source-line">警告对应原文 · 第 {{m.source_line_start}}–{{m.source_line_end}} 行</p><pre>{{m.raw_header}}{{m.raw_text}}</pre><button v-if="m.prefilter_filtered&&m.message_id&&canImport&&!m.is_deleted&&!preview.batch.is_deleted" class="small" @click="restorePrefilterMessage(m)" :disabled="loading">恢复为待处理</button></div></article><div v-if="!preview.records.length" class="empty"><FileText size="30"/><p>{{previewScreening==='filtered'?'没有已过滤的消息':previewScreening==='retained'?'没有保留的消息':'暂无消息'}}</p></div></div>
      <Pagination :page="preview.page" :total="preview.total" :disabled="loading" @change="n=>run(()=>loadPreview(preview.batch.id,n))"/>
      <p v-if="screeningSummary?.filtered" class="hint">{{preview.batch.confirmed_at?'如需保留某条过滤消息，可在原文下方恢复，再点击“生成草稿”重新整理。已有人工草稿与正式版本会保留。':'确认导入后，可查看原文并恢复误过滤的消息。'}}</p>
      <label v-if="preview.warnings.length&&!preview.batch.confirmed_at" class="checkbox-label"><input type="checkbox" v-model="acceptWarnings">已检查解析警告，确认保留原文并导入</label>
      <ExtractionOptions v-if="canImport&&!preview.batch.is_deleted" :profiles="profiles" v-model:profile="modelProfile" v-model:mode="extractMode" :disabled="loading"/>
      <div class="actions">
        <button @click="preview=null" :disabled="loading">关闭</button>
        <button v-if="!preview.batch.confirmed_at&&canImport&&!preview.batch.is_deleted" @click="confirmImport(false)" :disabled="loading||(preview.warnings.length&&!acceptWarnings)">仅导入</button>
        <button v-if="preview.batch.confirmed_at" @click="openChatFile(preview.batch)" :disabled="loading">查看文件聊天<ChevronRight size="15"/></button>
        <button v-if="canImport&&!preview.batch.is_deleted" class="primary" @click="confirmImport(true)" :disabled="loading||!modelConfigured||(!preview.batch.confirmed_at&&preview.warnings.length&&!acceptWarnings)"><Sparkles size="16"/>{{loading?'正在处理…':preview.batch.confirmed_at?'生成草稿':'确认导入并生成草稿'}}</button>
      </div>
    </section></div>
  </div>
</template>
