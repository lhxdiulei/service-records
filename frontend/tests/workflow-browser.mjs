// Deterministic UI regression: every API request is fulfilled from fixtures.
// Start Vite on 127.0.0.1:5173 first; no credentials or real model calls are used.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { loadChromium } from './browser-utils.mjs'
const chromium = await loadChromium()
const baseURL = process.env.WORKFLOW_BROWSER_URL || 'http://127.0.0.1:5173'
const artifacts = fileURLToPath(new URL('../test-results/workflows/', import.meta.url))
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
const results = []
const timestamp = '2026-10-16T09:00:00+08:00'
const rawQuestion = '客户：导出报表失败，应该如何处理？'
const rawAnswer = '客服：请更新客户端后重新导出。'
const filename = '流程回归样例.txt'
const clone = value => JSON.parse(JSON.stringify(value))

function fixture(options = {}) {
  const state = {
    uploaded: !!options.editor, confirmed: !!options.editor, restored: false,
    extractFailures: options.extractFailures || 0, saveFailures: options.saveFailures || 0,
    submitFailures: options.submitFailures || 0, job: null, calls: [], unexpected: [],
    pageErrors: [], showTicket: !!options.editor,
  }
  const saveGate = options.holdSave ? new Promise(resolve => { state.releaseSave = resolve }) : null
  const user = { id: 'user-1', username: 'fixture', display_name: '回归测试员', role: 'admin' }
  const revision = {
    id: 'revision-1', revision_no: 1, state: 'draft', state_version: 1,
    created_by: user.id, origin: 'ai', stale: false, title: '报表导出失败处理',
    problem_text: '客户导出报表失败', impact_text: '', handling_summary: '建议更新客户端',
    current_conclusion: '等待客户确认', status: 'waiting_customer',
    first_visible_message_id: 'message-1', first_question_message_id: 'message-1',
    date_basis: 'first_question', start_context_complete: true,
    claims: [{ claim_key: 'c1', text: '更新客户端后重新导出' }], next_actions: [],
    evidence: [{ field_key: 'problem', evidence_span_id: 'evidence-1', message_id: 'message-1', relation: 'supports', excerpt: rawQuestion }],
  }
  state.revisions = [revision]
  state.object = { id: 'ticket-1', ticket_no: 'TK-REGRESSION-001', issue_id: 'issue-1', version: 1, current_revision_id: null, is_deleted: false, updated_at: timestamp, source_filenames: [filename] }
  const summary = () => ({ version: 1, total: 3, retained: state.restored ? 3 : 2, filtered: state.restored ? 0 : 1, restored: state.restored ? 1 : 0, reasons: state.restored ? [] : [{ code: 'media_only', label: '仅表情或媒体占位', count: 1 }] })
  const batch = () => ({ id: 'batch-1', original_filename: filename, source_encoding: 'utf-8', message_count: 3, message_counts: { active: state.confirmed ? 3 : 0, deleted: 0, pending: 0, needs_review: state.restored ? 1 : 0 }, confirmed_at: state.confirmed ? timestamp : null, created_at: timestamp, version: state.confirmed ? 2 : 1, parse_version: 1, is_deleted: false, screening_summary: summary() })
  const messages = () => [
    { id: 'message-1', raw_text: rawQuestion, body_text: rawQuestion, sender_name_raw: '客户', sender_participant_id: 'person-1', sender_role: 'customer', sent_at: timestamp, relation: 'question' },
    { id: 'message-2', raw_text: rawAnswer, body_text: rawAnswer, sender_name_raw: '客服', sender_participant_id: 'person-2', sender_role: 'support', sent_at: timestamp, relation: 'answer' },
    { id: 'message-3', raw_text: '[表情]', body_text: '[表情]', sender_name_raw: '客户', sender_participant_id: 'person-1', sender_role: 'customer', sent_at: timestamp, relation: 'context' },
  ].map((message, i) => ({ ...message, kind: 'text', source_filename: filename, is_deleted: false, disposition: i === 2 ? state.restored ? 'needs_review' : 'ignored' : 'assigned', disposition_version: 1 }))
  const detail = () => ({ object: state.object, revisions: state.revisions, source_messages: messages().slice(0, 2), participants: [{ id: 'person-1', display_name: '客户' }, { id: 'person-2', display_name: '客服' }], reviews: [], notes: [], events: [] })
  const paginate = (items, url) => ({ items, total: items.length, page: Number(url.searchParams.get('page') || 1), page_size: Number(url.searchParams.get('page_size') || 10) })
  async function route(route) {
    const request = route.request(), url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(baseURL).origin) return route.continue()
      state.unexpected.push(`external ${request.url()}`)
      return route.abort()
    }
    const endpoint = url.pathname.replace('/api/v1', ''), method = request.method()
    const body = request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : null
    state.calls.push({ endpoint, method, body, version: request.headers()['if-match'] })
    const respond = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    const fail = (message, code = 'fixture_failure', status = 422) => respond({ detail: { message, code } }, status)
    if (endpoint === '/auth/csrf') return respond({ csrf_token: 'synthetic-only' })
    if (endpoint === '/auth/me') return respond(user)
    if (endpoint === '/overview') return respond({ tickets: state.showTicket ? 1 : 0, official_tickets: 0, qa: 0, official_qa: 0, reviews: 0, unassigned_messages: 0 })
    if (endpoint === '/issues') return respond([{ id: 'issue-1', label: '报表导出问题', lifecycle: 'active', created_at: timestamp }])
    if (endpoint === '/integrations/dify') return respond([{ id: 'local', configured: options.configured !== false }, { id: 'external', configured: false }])
    if (endpoint === '/imports' && method === 'POST') { state.uploaded = true; return respond({ batch: batch(), duplicate: false }, 201) }
    if (endpoint === '/imports' && method === 'GET') return respond(paginate(state.uploaded ? [batch()] : [], url))
    if (endpoint === '/imports/batch-1') return respond(batch())
    if (endpoint === '/imports/batch-1/preview') {
      let records = messages().map((message, index) => ({ sender: message.sender_name_raw, sent_at: message.sent_at, raw_text: message.raw_text, message_id: state.confirmed ? message.id : null, disposition_version: 1, prefilter_filtered: index === 2 && !state.restored, prefilter_restored: index === 2 && state.restored, prefilter_reason_label: index === 2 ? '仅表情或媒体占位' : null, is_deleted: false }))
      if (url.searchParams.get('screening') === 'filtered') records = records.filter(message => message.prefilter_filtered)
      if (url.searchParams.get('screening') === 'retained') records = records.filter(message => !message.prefilter_filtered)
      return respond({ batch: batch(), records, page: 1, page_size: 10, total: records.length, warnings: options.warnings ? [{ message: '样例存在无法确定的时间' }] : [], screening_summary: summary() })
    }
    if (endpoint === '/imports/batch-1/confirm' && method === 'POST') {
      if (options.warnings && !body.accept_warnings) return fail('需确认解析警告', 'warnings_unaccepted')
      assert.equal(state.confirmed, false, 'UI must not confirm an already imported file')
      state.confirmed = true
      return respond(batch())
    }
    if (endpoint === '/imports/batch-1/extractions' && method === 'POST') {
      assert.equal(state.confirmed, true, 'extraction must follow confirmation')
      if (state.extractFailures-- > 0) return fail('模型暂不可用，请重试', 'model_unavailable', 503)
      state.showTicket = true
      state.job = { id: 'job-0001', batch_id: 'batch-1', mode: body.mode, model_profile_snapshot: { id: body.profile }, state: 'succeeded', version: 1, created_at: timestamp, checkpoint: { messages_done: 3, messages_total: 3, extraction_done: 1, extraction_total: 1 } }
      return respond(state.job, 201)
    }
    if (endpoint === '/jobs') return respond(paginate(state.job ? [state.job] : [], url))
    if (endpoint === '/jobs/job-0001/records') return respond(paginate([{ record_kind: 'ticket', record_id: state.object.id, revision_id: state.revisions[0].id, revision_no: state.revisions[0].revision_no, record_no: state.object.ticket_no, title: state.revisions[0].title, state: state.revisions[0].state, action: 'created', is_deleted: false }], url))
    if (endpoint === '/messages') return respond(paginate(state.confirmed ? messages() : [], url))
    if (endpoint === '/messages/message-3/disposition' && method === 'PUT') { state.restored = true; return respond({ state: 'needs_review' }) }
    if (endpoint === '/tickets') return respond(paginate(state.showTicket ? [{ ...state.object, latest_revision: state.revisions[0] }] : [], url))
    if (['/qa', '/reviews', '/users'].includes(endpoint)) return respond(paginate([], url))
    if (endpoint === '/tickets/ticket-1') return respond(detail())
    if (endpoint === '/tickets/ticket-1/revisions' && method === 'POST') {
      if (saveGate) await saveGate
      if (state.saveFailures-- > 0) return fail('记录版本已变化', 'version_conflict', 409)
      const next = { ...clone(state.revisions[0]), id: `revision-${state.revisions.length + 1}`, revision_no: state.revisions.length + 1, state: 'draft', state_version: 1, origin: 'human', title: body.content.title, problem_text: body.content.problem, impact_text: body.content.impact, handling_summary: body.content.handling_summary, current_conclusion: body.content.current_conclusion, claims: body.content.claims, next_actions: body.content.next_actions }
      state.revisions[0].state = 'superseded'
      state.revisions.unshift(next)
      return respond(next, 201)
    }
    const submit = endpoint.match(/^\/tickets\/ticket-1\/revisions\/([^/]+)\/submit$/)
    if (submit && method === 'POST') {
      const exact = state.revisions.find(item => item.id === submit[1])
      assert.ok(exact, 'submit must identify an existing saved revision')
      assert.equal(exact.id, state.revisions[0].id, 'submit must use the newly saved version')
      if (state.submitFailures-- > 0) return fail('关键事实缺少证据', 'missing_evidence')
      exact.state = 'in_review'; exact.state_version++
      return respond(exact)
    }
    state.unexpected.push(`${method} ${endpoint}`)
    return fail(`未预期的测试请求：${method} ${endpoint}`, 'unexpected_request', 500)
  }
  return { state, route }
}

async function scenario(name, options, run) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, locale: 'zh-CN', serviceWorkers: 'block' })
  const { state, route } = fixture(options)
  await context.route('**/*', route)
  const page = await context.newPage()
  page.setDefaultTimeout(8000)
  page.on('pageerror', error => state.pageErrors.push(error.message))
  try {
    await page.goto(baseURL)
    await page.locator('.sidebar').waitFor()
    await run(page, state)
    assert.deepEqual(state.unexpected, [])
    assert.deepEqual(state.pageErrors, [])
    results.push({ name, passed: true })
    console.log(`PASS ${name}`)
  } catch (error) {
    const screenshot = path.join(artifacts, `${name}-failure.png`)
    await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {})
    results.push({ name, passed: false, error: error.stack || String(error), screenshot, unexpected: state.unexpected, pageErrors: state.pageErrors })
    console.error(`FAIL ${name}: ${error.message}`)
  } finally { await context.close() }
}

async function uploadPreview(page) {
  await page.locator('nav').getByRole('button', { name: '聊天记录', exact: true }).click()
  await page.getByLabel('选择聊天记录文件').setInputFiles({ name: filename, mimeType: 'text/plain', buffer: Buffer.from(`${rawQuestion}\n${rawAnswer}\n[表情]`) })
  await page.getByRole('button', { name: '上传并预览', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '导入预览' })
  await dialog.waitFor()
  return dialog
}

async function openEditor(page) {
  await page.locator('nav').getByRole('button', { name: '服务工单', exact: true }).click()
  await page.locator('.object-row').filter({ hasText: '报表导出失败处理' }).click()
  await page.getByLabel('工单标题', { exact: true }).waitFor()
}

function writes(state, pattern) { return state.calls.filter(call => call.method === 'POST' && pattern.test(call.endpoint)) }

try {
  await scenario('01-import-to-draft', {}, async (page, state) => {
    const dialog = await uploadPreview(page)
    await dialog.getByRole('button', { name: '确认导入并生成草稿', exact: true }).click()
    await page.getByRole('button', { name: '核对草稿', exact: true }).waitFor()
    assert.deepEqual(writes(state, /\/(confirm|extractions)$/).map(call => call.endpoint.split('/').at(-1)), ['confirm', 'extractions'])
    await page.screenshot({ path: path.join(artifacts, '01-file-drafts.png'), fullPage: true })
    await page.getByRole('button', { name: '核对草稿', exact: true }).click()
    await page.getByLabel('工单标题', { exact: true }).waitFor()
    assert.equal(await page.locator('[data-evidence-raw="message-1"]').textContent(), rawQuestion)
    assert.ok(await page.locator('[data-evidence-raw="message-1"]').isVisible())
    assert.ok(await page.getByRole('heading', { name: '审核与处理记录', exact: true }).isVisible())
    await page.getByRole('button', { name: '返回本文件', exact: true }).click()
    await page.getByRole('button', { name: '核对草稿', exact: true }).waitFor()
  })

  await scenario('02-extract-failure-retry', { extractFailures: 1 }, async (page, state) => {
    const dialog = await uploadPreview(page)
    await dialog.getByRole('button', { name: '确认导入并生成草稿', exact: true }).click()
    const imported = page.getByRole('dialog', { name: '导入结果' })
    await imported.getByRole('alert').filter({ hasText: '模型暂不可用，请重试' }).waitFor()
    await imported.getByRole('button', { name: '生成草稿', exact: true }).click()
    await page.getByRole('button', { name: '核对草稿', exact: true }).waitFor()
    assert.equal(writes(state, /\/confirm$/).length, 1)
    assert.equal(writes(state, /\/extractions$/).length, 2)
  })

  await scenario('03-parse-warning-confirmation', { warnings: true }, async (page, state) => {
    const dialog = await uploadPreview(page)
    const combined = dialog.getByRole('button', { name: '确认导入并生成草稿', exact: true })
    assert.ok(await combined.isDisabled())
    assert.ok(await dialog.getByRole('button', { name: '仅导入', exact: true }).isDisabled())
    assert.equal(writes(state, /\/(confirm|extractions)$/).length, 0)
    await dialog.getByLabel('已检查解析警告，确认保留原文并导入').check()
    assert.ok(await combined.isEnabled())
    await combined.click()
    await page.getByRole('button', { name: '核对草稿', exact: true }).waitFor()
    assert.equal(writes(state, /\/confirm$/)[0].body.accept_warnings, true)
  })

  await scenario('04-save-submit-retry', { editor: true, submitFailures: 1 }, async (page, state) => {
    await openEditor(page)
    await page.getByLabel('工单标题', { exact: true }).fill('核对后的报表导出工单')
    await page.getByRole('button', { name: '保存并提交审核', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '草稿已保存，但未提交审核' }).waitFor()
    assert.equal(writes(state, /\/revisions$/).length, 1)
    assert.equal(writes(state, /\/submit$/)[0].endpoint, '/tickets/ticket-1/revisions/revision-2/submit')
    assert.equal(await page.locator('.editor-toolbar select').inputValue(), 'revision-2')
    assert.equal(await page.getByLabel('工单标题', { exact: true }).inputValue(), '核对后的报表导出工单')
    await page.screenshot({ path: path.join(artifacts, '04-saved-awaiting-review.png'), fullPage: true })
    await page.getByRole('button', { name: '提交审核', exact: true }).click()
    await page.getByRole('button', { name: '批准此版本', exact: true }).waitFor()
    assert.equal(writes(state, /\/revisions$/).length, 1)
    assert.equal(writes(state, /\/submit$/).length, 2)
    assert.equal(state.object.current_revision_id, null, 'submission must not publish a formal version')
  })

  await scenario('05-save-failure-no-submit', { editor: true, saveFailures: 1 }, async (page, state) => {
    await openEditor(page)
    await page.getByLabel('工单标题', { exact: true }).fill('保留未保存的编辑')
    await page.getByRole('button', { name: '保存并提交审核', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '记录版本已变化' }).waitFor()
    assert.equal(writes(state, /\/revisions$/).length, 1)
    assert.equal(writes(state, /\/submit$/).length, 0)
    assert.equal(await page.getByLabel('工单标题', { exact: true }).inputValue(), '保留未保存的编辑')
    assert.equal(await page.locator('.editor-toolbar select').inputValue(), 'revision-1')
  })

  await scenario('06-import-without-model-restore', { configured: false }, async (page, state) => {
    const dialog = await uploadPreview(page)
    assert.ok(await dialog.getByRole('button', { name: '确认导入并生成草稿', exact: true }).isDisabled())
    await dialog.getByRole('button', { name: '仅导入', exact: true }).click()
    const imported = page.getByRole('dialog', { name: '导入结果' })
    await imported.waitFor()
    await imported.getByRole('button', { name: '恢复为待处理', exact: true }).waitFor()
    assert.ok(await imported.getByText('[表情]', { exact: true }).isVisible())
    assert.ok(await imported.getByRole('button', { name: '已过滤', exact: true }).isVisible())
    assert.equal(writes(state, /\/extractions$/).length, 0)
    await imported.getByRole('button', { name: '恢复为待处理', exact: true }).click()
    await imported.getByText('已恢复为待处理消息。', { exact: false }).waitFor()
    assert.equal(state.restored, true)
    assert.ok(await imported.getByText('[表情]', { exact: true }).isVisible())
    assert.equal(writes(state, /\/extractions$/).length, 0)
    await page.screenshot({ path: path.join(artifacts, '06-filter-restore.png'), fullPage: true })
  })

  await scenario('07-unsaved-navigation', { editor: true }, async page => {
    await openEditor(page)
    await page.getByLabel('工单标题', { exact: true }).fill('离开前必须保护的编辑')
    let prompts = 0
    const dismiss = dialog => { prompts++; assert.match(dialog.message(), /未保存/); return dialog.dismiss() }
    page.once('dialog', dismiss)
    await page.locator('nav').getByRole('button', { name: '聊天记录', exact: true }).click()
    assert.equal(prompts, 1)
    assert.equal(await page.getByLabel('工单标题', { exact: true }).inputValue(), '离开前必须保护的编辑')
    page.once('dialog', dialog => { prompts++; return dialog.accept() })
    await page.locator('nav').getByRole('button', { name: '聊天记录', exact: true }).click()
    await page.getByLabel('选择聊天记录文件').waitFor()
    assert.equal(prompts, 2)
  })

  await scenario('08-pending-save-locks-editor', { editor: true, holdSave: true }, async (page, state) => {
    await openEditor(page)
    await page.getByLabel('工单标题', { exact: true }).fill('提交时锁定编辑内容')
    const requested = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/tickets/ticket-1/revisions')
    await page.getByRole('button', { name: '保存并提交审核', exact: true }).click()
    await requested
    try {
      assert.ok(await page.getByLabel('工单标题', { exact: true }).isDisabled(), 'pending save must prevent edits being silently overwritten')
      assert.ok(await page.locator('nav').getByRole('button', { name: '聊天记录', exact: true }).isDisabled())
      assert.equal(writes(state, /\/submit$/).length, 0, 'submit must wait for the save response')
    } finally { state.releaseSave() }
    await page.getByRole('button', { name: '批准此版本', exact: true }).waitFor()
    assert.equal(writes(state, /\/revisions$/)[0].body.content.title, '提交时锁定编辑内容')
    assert.equal(writes(state, /\/submit$/).length, 1)
  })
} finally {
  await browser.close()
  await writeFile(path.join(artifacts, 'results.json'), JSON.stringify({ url: baseURL, syntheticAPI: true, results }, null, 2))
}
const failed = results.filter(result => !result.passed)
console.log(`${results.length - failed.length}/${results.length} browser scenarios passed; artifacts: ${artifacts}`)
if (failed.length) process.exitCode = 1
