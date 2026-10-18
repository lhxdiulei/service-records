// Editor regressions against synthetic API fixtures only. No production data,
// login credentials, model requests or writes reach the application backend.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { loadChromium } from './browser-utils.mjs'
const chromium = await loadChromium()
const baseURL = process.env.EDITOR_BROWSER_URL || 'http://127.0.0.1:5173'
const artifacts = fileURLToPath(new URL('../test-results/editor/', import.meta.url))
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
const results = []
const stamp = '2026-10-16T09:00:00+08:00'
const rawAnswer = '> 请重启😀\r\n请重启😀'
const answerExcerpt = '请重启😀'
const clone = value => JSON.parse(JSON.stringify(value))

function fixture(options = {}) {
  const kind = options.kind || 'ticket', plural = kind === 'ticket' ? 'tickets' : 'qa', objectId = `${kind}-1`
  const state = { calls: [], unexpected: [], pageErrors: [] }
  const user = { id: 'user-1', username: 'fixture', display_name: '合成回归测试员', role: 'admin' }
  const participants = [{ id: 'customer', display_name: '客户' }, { id: 'alice', display_name: '小王' }, { id: 'bob', display_name: '小李' }]
  const makeMessage = (id, author, raw, sentAt, relation, extra = {}) => ({
    id, sender_participant_id: author, sender_name_raw: participants.find(p => p.id === author)?.display_name || '未知成员',
    raw_text: raw, body_text: raw, direct_body_spans: [{ start_cp: 0, end_cp: Array.from(raw).length }],
    sent_at: sentAt, relation, source_filename: '编辑体验合成回归.txt', is_deleted: false, ...extra,
  })
  state.messages = [
    makeMessage('deleted', 'customer', '已删除的更早上下文', '2025-01-01T00:00:00+08:00', 'context', { is_deleted: true }),
    makeMessage('invalid-time', 'customer', '时间未确认的记录', 'invalid-time', 'context'),
    makeMessage('question', 'customer', '导出失败如何处理？', stamp, options.noQuestion ? 'context' : 'question'),
    makeMessage('earliest', 'customer', '这是最早有效上下文', '2026-10-15T08:00:00+08:00', 'context'),
    makeMessage('answer', 'alice', rawAnswer, '2026-10-16T09:01:00+08:00', 'answer', { direct_body_spans: [{ start_cp: 8, end_cp: 12 }] }),
    makeMessage('question-only', 'bob', '需要重启吗？', stamp, 'question'),
  ]
  if (options.noQuestion) state.messages.forEach(m => { if (m.relation === 'question') m.relation = 'context' })
  if (options.noDates) state.messages.forEach(m => { if (!m.is_deleted) m.sent_at = null })
  if (options.uncertainQuestion) {
    const uncertain = state.messages.find(m => m.id === 'invalid-time')
    uncertain.relation = 'question'
    uncertain.sent_at = options.uncertainQuestion === 'missing' ? null : 'invalid-time'
  }
  const binding = (id, messageId, start, end, field, relation = 'supports') => ({
    evidence_span_id: id, message_id: messageId, start_cp: start, end_cp: end, field_key: field, relation,
    excerpt: Array.from(state.messages.find(m => m.id === messageId).raw_text).slice(start, end).join(''),
  })
  const evidence = kind === 'qa' ? [
    binding('quoted', 'answer', 2, 6, 'answer'),
    binding('direct', 'answer', 8, 12, 'answer_claims.c1'),
    binding('question-only', 'question-only', 0, 6, 'question'),
  ] : [binding('problem', 'question', 0, 9, 'problem'), binding('fact', 'answer', 8, 12, 'claims.c1')]
  if (options.factProblem === 'missing') evidence.splice(evidence.findIndex(e => e.field_key.endsWith('.c1')), 1)
  if (options.factProblem === 'conflict') evidence.push(binding('contradiction', 'answer', 8, 12, kind === 'qa' ? 'answer_claims.c1' : 'claims.c1', 'contradicts'))
  const revision = {
    id: 'revision-1', revision_no: 1, state: options.inReview ? 'in_review' : 'draft', state_version: 1, created_by: user.id,
    origin: 'ai', stale: false, title: '编辑体验回归工单', problem_text: '客户导出失败', impact_text: '',
    handling_summary: '建议重启', current_conclusion: '等待确认', status: 'waiting_customer',
    first_visible_message_id: 'question', first_question_message_id: options.noQuestion ? null : 'question',
    date_basis: options.noQuestion ? 'first_visible_context' : 'first_question', start_context_complete: !options.noQuestion,
    claims: [{ claim_key: 'c1', text: '建议重启客户端' }], next_actions: [],
    question: '导出失败应如何处理？', answer: '请重启客户端', answer_state: 'supported', applicability: '',
    answer_claims: [{ claim_key: 'c1', text: '建议重启客户端' }], contributors: [], issue_ids: ['issue-1'], evidence,
  }
  if (options.savedDate) {
    revision.ticket_date = options.savedDate
    revision.first_question_at = `${options.savedDate}T09:00:00+08:00`
    revision.first_visible_at = `${options.savedDate}T09:00:00+08:00`
  }
  state.revisions = options.newTicket ? [] : [revision]
  state.object = { id: objectId, ticket_no: 'TK-EDITOR-001', qa_no: 'QA-EDITOR-001', issue_id: 'issue-1', version: 1, current_revision_id: null, is_deleted: false, updated_at: stamp, source_filenames: ['编辑体验合成回归.txt'] }
  const spans = new Map(evidence.map(e => [e.evidence_span_id, e]))
  const detail = () => ({ object: state.object, revisions: state.revisions, source_messages: state.messages, participants, reviews: [], notes: [], events: [] })
  const paginate = (items, url) => ({ items, total: items.length, page: Number(url.searchParams.get('page') || 1), page_size: 10 })
  async function route(route) {
    const request = route.request(), url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(baseURL).origin) return route.continue()
      state.unexpected.push(`external ${request.url()}`); return route.abort()
    }
    const endpoint = url.pathname.replace('/api/v1', ''), method = request.method()
    const body = request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : null
    state.calls.push({ endpoint, method, body })
    const respond = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    const fail = (message, code = 'fixture_error', status = 422) => respond({ detail: { message, code } }, status)
    if (endpoint === '/auth/csrf') return respond({ csrf_token: 'synthetic-only' })
    if (endpoint === '/auth/me') return respond(user)
    if (endpoint === '/overview') return respond({ tickets: kind === 'ticket' ? 1 : 0, official_tickets: 0, qa: kind === 'qa' ? 1 : 0, official_qa: 0, reviews: 0, unassigned_messages: 0 })
    if (endpoint === '/issues') return respond([{ id: 'issue-1', label: '编辑体验回归问题', lifecycle: 'active', created_at: stamp }])
    if (endpoint === '/integrations/dify') return respond([{ id: 'local', configured: true }, { id: 'external', configured: false }])
    if (['/imports', '/messages', '/jobs', '/reviews', '/users'].includes(endpoint)) return respond(paginate([], url))
    if (['/tickets', '/qa'].includes(endpoint)) return respond(paginate(endpoint === `/${plural}` ? [{ ...state.object, latest_revision: state.revisions[0] }] : [], url))
    if (endpoint === `/${plural}/${objectId}`) return respond(detail())
    if (endpoint === '/evidence-spans' && method === 'POST') {
      const message = state.messages.find(m => m.id === body.message_id && !m.is_deleted)
      assert.ok(message, 'new citation must use an undeleted source')
      const points = Array.from(message.raw_text), excerpt = Array.from(body.exact_excerpt)
      const matches = []
      for (let start = 0; start + excerpt.length <= points.length; start++) {
        if (points.slice(start, start + excerpt.length).join('') === body.exact_excerpt) matches.push(start)
      }
      const start = matches[body.occurrence - 1]
      assert.notEqual(start, undefined, 'citation must identify an exact occurrence')
      const span = { id: `new-evidence-${spans.size}`, evidence_span_id: `new-evidence-${spans.size}`, message_id: message.id, start_cp: start, end_cp: start + excerpt.length, excerpt: body.exact_excerpt }
      spans.set(span.id, span)
      return respond(span, 201)
    }
    if (endpoint === `/${plural}/${objectId}/revisions` && method === 'POST') {
      const content = body.content
      const next = {
        ...clone(state.revisions[0] || revision), ...content, id: `revision-${state.revisions.length + 1}`, revision_no: state.revisions.length + 1,
        state: 'draft', state_version: 1, origin: 'human',
        problem_text: content.problem, impact_text: content.impact,
        evidence: body.evidence.map(item => ({ ...spans.get(item.evidence_span_id), ...item })),
      }
      if (state.revisions[0]) state.revisions[0].state = 'superseded'
      state.revisions.unshift(next)
      return respond(next, 201)
    }
    const action = endpoint.match(new RegExp(`^/${plural}/${objectId}/revisions/([^/]+)/(submit|approve|reject)$`))
    if (action && method === 'POST') {
      const exact = state.revisions.find(r => r.id === action[1])
      assert.ok(exact)
      if (action[2] === 'approve' && exact.date_basis === 'first_visible_context' && !body.accept_incomplete_start) return fail('需要确认缺少原始提问', 'incomplete_start')
      exact.state = { submit: 'in_review', approve: 'approved', reject: 'rejected' }[action[2]]
      exact.state_version++
      if (action[2] === 'approve') state.object.current_revision_id = exact.id
      return respond(exact)
    }
    state.unexpected.push(`${method} ${endpoint}`)
    return fail(`未预期的合成请求：${method} ${endpoint}`, 'unexpected_request', 500)
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
    await page.locator('.sidebar nav').getByRole('button', { name: options.kind === 'qa' ? '知识 QA' : '服务工单', exact: true }).click()
    await page.locator('.object-row').first().click()
    await page.getByRole('heading', { name: options.kind === 'qa' ? '知识内容' : '工单内容', exact: true }).waitFor()
    await run(page, state)
    assert.deepEqual(state.unexpected, [])
    assert.deepEqual(state.pageErrors, [])
    results.push({ name, passed: true }); console.log(`PASS ${name}`)
  } catch (error) {
    const screenshot = path.join(artifacts, `${name}-failure.png`)
    await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {})
    results.push({ name, passed: false, error: error.stack || String(error), screenshot, unexpected: state.unexpected, pageErrors: state.pageErrors })
    console.error(`FAIL ${name}: ${error.message}`)
  } finally { await context.close() }
}

const writes = (state, pattern) => state.calls.filter(call => call.method === 'POST' && pattern.test(call.endpoint))
async function save(page, state) {
  const count = writes(state, /\/revisions$/).length
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await page.getByText('草稿已保存，尚未提交审核', { exact: true }).waitFor()
  assert.equal(writes(state, /\/revisions$/).length, count + 1)
  return writes(state, /\/revisions$/).at(-1).body
}

try {
  await scenario('01-automatic-date-and-manual-correction', {}, async (page, state) => {
    assert.equal(await page.getByRole('combobox', { name: '首次可见消息', exact: true }).count(), 0)
    const options = page.getByText('校正日期依据', { exact: true })
    const details = options.locator('..')
    assert.equal(await details.getAttribute('open'), null)
    await options.click()
    await page.getByRole('combobox', { name: '原始提问消息', exact: true }).fill('这是最早有效上下文')
    await page.getByRole('option').filter({ hasText: '这是最早有效上下文' }).click()
    const body = await save(page, state)
    assert.equal(body.content.first_visible_message_id, 'earliest')
    assert.equal(body.content.first_question_message_id, 'earliest')
    assert.equal(body.content.date_basis, 'first_question')
    await page.screenshot({ path: path.join(artifacts, '01-dates-and-content.png'), fullPage: true })
  })

  await scenario('02-precise-repeated-emoji-citation', {}, async (page, state) => {
    await page.locator('.field-heading').filter({ hasText: '当前结论' }).getByRole('button', { name: '关联原文（可选）', exact: true }).click()
    const source = page.locator('[data-evidence-raw="answer"]')
    await source.evaluate((element, excerpt) => {
      const raw = element.textContent, start = raw.lastIndexOf(excerpt)
      const end = start + excerpt.length, walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
      const range = document.createRange()
      let cursor = 0, started = false, node
      while ((node = walker.nextNode())) {
        const next = cursor + node.textContent.length
        if (!started && start >= cursor && start <= next) { range.setStart(node, start - cursor); started = true }
        if (started && end <= next) { range.setEnd(node, end - cursor); break }
        cursor = next
      }
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
      element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    }, answerExcerpt)
    await page.getByRole('button', { name: '引用选中文字', exact: true }).click()
    await page.getByText('已关联「当前结论」的原文，保存草稿后生效', { exact: true }).waitFor()
    assert.deepEqual(writes(state, /\/evidence-spans$/).at(-1).body, { message_id: 'answer', exact_excerpt: answerExcerpt, occurrence: 2 })
    const body = await save(page, state)
    const citation = body.evidence.find(e => e.field_key === 'current_conclusion')
    assert.ok(citation)
    const persisted = state.revisions[0].evidence.find(e => e.evidence_span_id === citation.evidence_span_id)
    assert.equal(persisted.start_cp, 8); assert.equal(persisted.end_cp, 12)
    assert.equal(await page.locator('[data-evidence-raw="answer"]').textContent(), rawAnswer)
    await page.screenshot({ path: path.join(artifacts, '02-exact-citation.png'), fullPage: true })
  })

  await scenario('03-contributor-suggestions-require-adoption', { kind: 'qa' }, async (page, state) => {
    const picker = page.getByRole('region', { name: '核心贡献者', exact: true })
    assert.equal(await picker.locator('.contributor-picker__member').count(), 0)
    assert.match(await picker.locator('.contributor-picker__suggestions').innerText(), /小王/)
    assert.doesNotMatch(await picker.locator('.contributor-picker__suggestions').innerText(), /小李/)
    await picker.getByRole('button', { name: '采用建议', exact: true }).click()
    let body = await save(page, state)
    assert.deepEqual(body.content.contributors, [{ participant_id: 'alice', contribution: '提供关键解答', evidence_span_ids: ['direct'] }])
    await picker.getByRole('button', { name: '移除贡献者小王', exact: true }).click()
    body = await save(page, state)
    assert.deepEqual(body.content.contributors, [])
    assert.equal(await picker.locator('.contributor-picker__member').count(), 0)
    assert.ok(await picker.getByRole('button', { name: '采用建议', exact: true }).isVisible())
    await page.screenshot({ path: path.join(artifacts, '03-contributor-recommendations.png'), fullPage: true })
  })

  await scenario('04-supported-facts-collapsed-and-removal-cleans-bindings', {}, async (page, state) => {
    const summary = page.locator('summary').filter({ hasText: '关键事实与依据' })
    const details = summary.locator('..')
    assert.equal(await details.getAttribute('open'), null)
    await summary.click()
    await details.getByRole('button', { name: /移除.*事实/ }).click()
    const body = await save(page, state)
    assert.deepEqual(body.content.claims, [])
    assert.ok(body.evidence.every(e => e.field_key !== 'claims.c1'))
    assert.equal(await page.locator('[data-evidence-raw="answer"]').textContent(), rawAnswer)
  })

  for (const problem of ['missing', 'conflict']) {
    await scenario(`05-fact-${problem}-expanded`, { factProblem: problem }, async page => {
      const summary = page.locator('summary').filter({ hasText: '关键事实与依据' })
      assert.notEqual(await summary.locator('..').getAttribute('open'), null)
      assert.match(await summary.locator('..').innerText(), problem === 'conflict' ? /矛盾/ : /缺少|待补充|待核对/)
    })
  }

  await scenario('06-save-submit-still-requires-explicit-approval', {}, async (page, state) => {
    await page.getByLabel('工单标题', { exact: true }).fill('第二阶段审核仍显式')
    await page.getByRole('button', { name: '保存并提交审核', exact: true }).click()
    await page.getByRole('button', { name: '批准此版本', exact: true }).waitFor()
    assert.equal(writes(state, /\/revisions$/).length, 1)
    assert.equal(writes(state, /\/submit$/).at(-1).endpoint, '/tickets/ticket-1/revisions/revision-2/submit')
    assert.equal(writes(state, /\/approve$/).length, 0)
    assert.equal(state.object.current_revision_id, null)
    await page.getByRole('button', { name: '批准此版本', exact: true }).click()
    await page.getByText('审核通过，已更新正式版本', { exact: true }).waitFor()
    assert.equal(state.object.current_revision_id, 'revision-2')
  })

  await scenario('07-missing-question-confirmation-preserved', { noQuestion: true, inReview: true }, async (page, state) => {
    const confirm = page.getByLabel('确认缺少原始提问，按首次可见上下文记录', { exact: true })
    assert.ok(await confirm.isVisible())
    assert.equal(await confirm.isChecked(), false)
    await page.getByRole('button', { name: '批准此版本', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: /确认缺少原始提问/ }).waitFor()
    assert.equal(state.object.current_revision_id, null)
    await confirm.check()
    await page.getByRole('button', { name: '批准此版本', exact: true }).click()
    await page.getByText('审核通过，已更新正式版本', { exact: true }).waitFor()
    assert.equal(writes(state, /\/approve$/).at(-1).body.accept_incomplete_start, true)
  })

  await scenario('08-no-valid-date-prevents-unsupported-save', { noDates: true }, async (page, state) => {
    await page.getByLabel('工单标题', { exact: true }).fill('时间未知仍需人工确认')
    await page.getByRole('button', { name: '保存并提交审核', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '来源消息没有有效时间' }).waitFor()
    assert.equal(writes(state, /\/revisions$/).length, 0)
    assert.equal(writes(state, /\/submit$/).length, 0)
  })

  for (const uncertainQuestion of ['invalid', 'missing']) {
    await scenario(`09-new-ticket-${uncertainQuestion}-question-time`, { newTicket: true, uncertainQuestion }, async (page, state) => {
      const summary = page.locator('.date-summary')
      assert.equal(await summary.locator('select').inputValue(), 'first_visible_context')
      assert.notEqual(await summary.locator('details').getAttribute('open'), null)
      assert.match(await summary.innerText(), /部分提问缺少有效时间，无法自动确定最早提问/)
      assert.match(await summary.innerText(), /工单日期 · 首次可见上下文/)
      const confirmation = page.getByLabel('确认缺少原始提问，按首次可见上下文记录', { exact: true })
      assert.ok(await confirmation.isVisible())
      assert.equal(await confirmation.isChecked(), false)
      assert.equal(writes(state, /\/revisions$/).length, 0)
      const body = await save(page, state)
      assert.equal(body.content.date_basis, 'first_visible_context')
      assert.equal(body.content.first_question_message_id, null, 'later dated question must not be guessed as the first question')
      assert.equal(body.content.first_visible_message_id, 'earliest')
      assert.equal(writes(state, /\/(submit|approve)$/).length, 0)
    })
  }

  await scenario('10-saved-date-remains-snapshot-when-sources-change', { savedDate: '2026-10-14' }, async (page, state) => {
    const summary = page.locator('.date-summary')
    const displayed = await summary.locator('strong').innerText()
    assert.match(displayed, /2026-10-14/)
    assert.match(displayed, /已保存版本/)
    assert.doesNotMatch(displayed, /2026[/-]10[/-]16/)
    assert.match(await summary.locator('.hint').innerText(), /2026[/-]10[/-]15/)
    assert.equal(state.messages.find(message => message.id === 'question').sent_at, stamp)
    assert.equal(writes(state, /\/revisions$/).length, 0, 'viewing history must not rewrite its saved date')
    await summary.getByRole('button', { name: '查看日期原文', exact: true }).click()
    assert.ok(await page.locator('[data-evidence-raw="question"]').isVisible())
    assert.match(await summary.locator('strong').innerText(), /2026-10-14/)
  })
} finally {
  await browser.close()
  await writeFile(path.join(artifacts, 'results.json'), JSON.stringify({ url: baseURL, syntheticAPI: true, results }, null, 2))
}
const failed = results.filter(result => !result.passed)
console.log(`${results.length - failed.length}/${results.length} editor browser scenarios passed; artifacts: ${artifacts}`)
if (failed.length) process.exitCode = 1
