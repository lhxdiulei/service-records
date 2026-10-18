// Navigation and list regressions use intercepted, synthetic API fixtures only.
// Every /api/ request is fulfilled here; external traffic is blocked.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { loadChromium } from './browser-utils.mjs'
const chromium = await loadChromium()
const baseURL = process.env.NAVIGATION_BROWSER_URL || 'http://127.0.0.1:5173'
const artifacts = fileURLToPath(new URL('../test-results/navigation/', import.meta.url))
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
const results = []
const timestamp = '2026-10-16T09:00:00+08:00'
const filename = '导航回归聊天.txt'

function fixture(options = {}) {
  const state = { calls: [], unexpected: [], pageErrors: [], tickets: [], qa: [], dispositionEntered: false }
  const user = { id: 'user-1', username: 'fixture', display_name: '合成回归测试员', role: options.role || 'admin' }
  const dispositionGate = options.holdDisposition ? new Promise(resolve => { state.releaseDisposition = resolve }) : null
  const searchGate = options.holdSearch ? new Promise(resolve => { state.releaseSearch = resolve }) : null
  const issues = [{ id: 'issue-1', label: '报表导出问题', lifecycle: 'active', version: 1, created_at: timestamp }]
  const message = (number, text) => ({ id: `message-${number}`, raw_text: text, body_text: text, sender_name_raw: `成员${number}`, sender_participant_id: `person-${number}`, sender_role: number === 1 ? 'customer' : 'support', kind: 'text', sent_at: timestamp, relation: number === 1 ? 'question' : 'answer', source_filename: filename, is_deleted: false, disposition: 'pending', disposition_version: 1 })
  state.messages = [message(1, '导出报表时发生错误，请帮忙处理。'), message(2, '请更新客户端再重试。')]
  state.messages[1].disposition_version = 7
  const batch = () => ({ id: 'batch-1', original_filename: filename, source_encoding: 'utf-8', message_count: 2, message_counts: { active: state.messages.filter(m => !m.is_deleted).length, deleted: state.messages.filter(m => m.is_deleted).length, pending: state.messages.filter(m => m.disposition === 'pending').length }, confirmed_at: timestamp, created_at: timestamp, version: 2, parse_version: 1, is_deleted: false })
  function record(kind, number) {
    const id = `${kind}-${number}`
    const revision = { id: `${id}-revision-1`, revision_no: 1, state: 'draft', state_version: 1, created_by: user.id, origin: 'human', stale: false, title: `工单 ${String(number).padStart(2, '0')} 导出处理`, question: `知识 ${String(number).padStart(2, '0')} 如何导出`, answer: '', answer_state: 'no_answer', applicability: '', answer_claims: [], contributors: [], problem_text: '导出失败', impact_text: '', handling_summary: '', current_conclusion: '', status: 'open', first_visible_message_id: 'message-1', first_question_message_id: 'message-1', date_basis: 'first_question', start_context_complete: true, claims: [], next_actions: [], evidence: [], issue_ids: ['issue-1'] }
    return { id, ticket_no: kind === 'ticket' ? `TK-${number}` : undefined, qa_no: kind === 'qa' ? `QA-${number}` : undefined, issue_id: 'issue-1', version: 1, delete_version: 0, is_deleted: false, current_revision_id: null, updated_at: timestamp, source_filenames: [filename], latest_revision: revision }
  }
  for (let n = 1; n <= (options.count || 1); n++) { state.tickets.push(record('ticket', n)); state.qa.push(record('qa', n)) }
  const detail = object => ({ object, revisions: [object.latest_revision], source_messages: state.messages, participants: [{ id: 'person-1', display_name: '成员1' }, { id: 'person-2', display_name: '成员2' }], reviews: [], notes: [], events: [] })
  const paginate = (items, url) => {
    const page = Number(url.searchParams.get('page') || 1), pageSize = Number(url.searchParams.get('page_size') || 10)
    return { items: items.slice((page - 1) * pageSize, page * pageSize), total: items.length, page, page_size: pageSize }
  }
  async function route(route) {
    const request = route.request(), url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(baseURL).origin) return route.continue()
      state.unexpected.push(`external ${request.url()}`); return route.abort()
    }
    const endpoint = url.pathname.replace('/api/v1', ''), method = request.method()
    const body = request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : null
    state.calls.push({ endpoint, method, body, query: Object.fromEntries(url.searchParams), version: request.headers()['if-match'] })
    const respond = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (endpoint === '/auth/csrf') return respond({ csrf_token: 'synthetic-only' })
    if (endpoint === '/auth/me') return respond(user)
    if (endpoint === '/overview') return respond({ tickets: state.tickets.filter(o => !o.is_deleted).length, official_tickets: 0, qa: state.qa.filter(o => !o.is_deleted).length, official_qa: 0, reviews: 0, unassigned_messages: 2 })
    if (endpoint === '/issues' && method === 'GET') return respond(issues)
    if (endpoint === '/integrations/dify') return respond([{ id: 'local', configured: true }, { id: 'external', configured: false }])
    if (endpoint === '/imports') return respond(paginate([batch()], url))
    if (endpoint === '/imports/batch-1') return respond(batch())
    if (['/jobs', '/reviews', '/users'].includes(endpoint)) return respond(paginate([], url))
    if (endpoint === '/messages') {
      const deleted = url.searchParams.get('deleted') === 'true', filter = url.searchParams.get('state'), query = url.searchParams.get('q') || ''
      if (searchGate && query) { state.searchEntered = true; await searchGate }
      return respond(paginate(state.messages.filter(m => m.is_deleted === deleted && (!filter || m.disposition === filter) && `${m.raw_text} ${m.sender_name_raw}`.includes(query)), url))
    }
    if (['/tickets', '/qa'].includes(endpoint) && method === 'GET') {
      const collection = endpoint === '/tickets' ? state.tickets : state.qa
      const deleted = url.searchParams.get('deleted') === 'true', query = url.searchParams.get('q') || ''
      return respond(paginate(collection.filter(o => o.is_deleted === deleted && `${o.latest_revision.title} ${o.latest_revision.question}`.includes(query)), url))
    }
    if (endpoint === '/qa' && method === 'POST') {
      assert.deepEqual(body.issue_ids, ['issue-1'])
      const object = record('qa', state.qa.length + 1)
      Object.assign(object.latest_revision, body.content)
      state.qa.push(object)
      return respond(detail(object), 201)
    }
    const objectDetail = endpoint.match(/^\/(tickets|qa)\/([^/]+)$/)
    if (objectDetail && method === 'GET') {
      const collection = objectDetail[1] === 'tickets' ? state.tickets : state.qa
      const object = collection.find(o => o.id === objectDetail[2]); assert.ok(object)
      return respond(detail(object))
    }
    const deletion = endpoint.match(/^\/records\/(ticket|qa|message)\/([^/]+)(\/restore)?$/)
    if (deletion && (method === 'DELETE' || method === 'POST')) {
      const collection = deletion[1] === 'ticket' ? state.tickets : deletion[1] === 'qa' ? state.qa : state.messages
      const object = collection.find(o => o.id === deletion[2]); assert.ok(object)
      assert.equal(method, deletion[3] ? 'POST' : 'DELETE')
      object.is_deleted = !deletion[3]; object.delete_version = (object.delete_version || 0) + 1
      return respond({ delete_version: object.delete_version, is_deleted: object.is_deleted })
    }
    const disposition = endpoint.match(/^\/messages\/([^/]+)\/disposition$/)
    if (disposition && method === 'PUT') {
      const message = state.messages.find(m => m.id === disposition[1]); assert.ok(message)
      state.dispositionEntered = true
      if (dispositionGate) await dispositionGate
      message.disposition = body.state; message.disposition_reason = body.reason; message.disposition_version++
      return respond({ state: body.state })
    }
    if (endpoint === '/issues' && method === 'POST') {
      assert.ok(body.title.trim()); assert.ok(body.messages.length)
      for (const link of body.messages) { const m = state.messages.find(m => m.id === link.message_id); assert.ok(m); m.disposition = 'assigned'; m.relation = link.relation }
      const issue = { id: `issue-${issues.length + 1}`, label: body.title, lifecycle: 'active', version: 1, created_at: timestamp }
      const ticket = record('ticket', state.tickets.length + 1)
      ticket.issue_id = issue.id
      ticket.latest_revision.issue_ids = [issue.id]
      ticket.latest_revision.title = body.title
      issues.push(issue); state.tickets.push(ticket)
      return respond({ issue, ticket }, 201)
    }
    state.unexpected.push(`${method} ${endpoint}`)
    return respond({ detail: { message: `未预期的合成请求：${method} ${endpoint}`, code: 'unexpected_request' } }, 500)
  }
  return { state, route }
}

async function scenario(name, options, run) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1440, height: 1080 }, locale: 'zh-CN', serviceWorkers: 'block' })
  const { state, route } = fixture(options)
  await context.route('**/*', route)
  const page = await context.newPage(); page.setDefaultTimeout(8000)
  page.on('pageerror', error => state.pageErrors.push(error.message))
  try {
    await page.goto(baseURL); await page.locator('.sidebar').waitFor({ state: 'attached' })
    await run(page, state)
    assert.deepEqual(state.unexpected, []); assert.deepEqual(state.pageErrors, [])
    results.push({ name, passed: true }); console.log(`PASS ${name}`)
  } catch (error) {
    const screenshot = path.join(artifacts, `${name}-failure.png`)
    await page.screenshot({ path: screenshot, fullPage: true }).catch(() => {})
    results.push({ name, passed: false, error: error.stack || String(error), screenshot, unexpected: state.unexpected, pageErrors: state.pageErrors })
    console.error(`FAIL ${name}: ${error.message}`)
  } finally { state.releaseDisposition?.(); state.releaseSearch?.(); await context.close() }
}

const writes = (state, pattern) => state.calls.filter(call => call.method !== 'GET' && pattern.test(call.endpoint))
const listCalls = (state, endpoint) => state.calls.filter(call => call.method === 'GET' && call.endpoint === endpoint)
async function openNavigation(page) {
  if (await page.locator('.sidebar').isVisible()) return
  await page.getByRole('button', { name: '打开导航', exact: true }).click()
  await page.getByRole('dialog', { name: '工作区导航', exact: true }).waitFor()
}
async function navigate(page, label) {
  await openNavigation(page)
  await page.locator('.sidebar nav').getByRole('button', { name: label, exact: true }).click()
  await page.getByRole('heading', { name: label === '设置' ? '系统设置' : label, exact: true }).waitFor()
}
async function openChat(page) {
  await navigate(page, '聊天记录')
  await page.getByRole('button', { name: '打开文件', exact: true }).click()
  await page.locator('.message-row').first().waitFor()
}
const filterDisclosure = page => page.locator('main details').filter({ has: page.locator('summary').filter({ hasText: /^筛选/ }) }).first()
async function expandFilters(page) {
  const details = filterDisclosure(page)
  if (await details.getAttribute('open') === null) await details.locator('summary').click()
  return details
}
async function waitList(page) { await page.locator('.object-row').first().waitFor() }
async function waitUntil(check) {
  const until = Date.now() + 8000
  while (!check()) { if (Date.now() > until) throw new Error('Timed out waiting for synthetic request state'); await new Promise(resolve => setTimeout(resolve, 20)) }
}

try {
  await scenario('01-primary-navigation-and-tools', {}, async page => {
    const nav = page.locator('.sidebar nav')
    assert.equal(await nav.getByRole('button').count(), 5)
    assert.equal(await nav.getByRole('button', { name: 'AI 任务', exact: true }).isVisible(), false)
    const tools = page.locator('.sidebar details').filter({ hasText: '工具与设置' })
    assert.equal(await tools.getAttribute('open'), null)
    await tools.locator('summary').click()
    assert.equal(await nav.getByRole('button').count(), 7)
    await navigate(page, 'AI 任务')
    await navigate(page, '设置')
    await page.getByRole('heading', { name: '用户列表', exact: true }).waitFor()
    assert.ok(await page.getByRole('button', { name: '新增账号', exact: true }).isVisible())
    await page.screenshot({ path: path.join(artifacts, '01-tools-expanded.png'), fullPage: true })
  })

  await scenario('02-single-page-hides-navigation', {}, async page => {
    await navigate(page, '服务工单'); await waitList(page)
    const pagination = page.locator('main').getByRole('navigation', { name: '分页', exact: true })
    assert.equal(await pagination.getByRole('button').count(), 0)
    assert.match(await pagination.innerText(), /共 1 条/)
    await navigate(page, '审核中心')
    assert.equal(await page.locator('main').getByRole('navigation', { name: '分页', exact: true }).getByRole('button').count(), 0)
  })

  await scenario('03-multipage-and-independent-list-memory', { count: 25 }, async (page, state) => {
    await navigate(page, '服务工单'); await waitList(page)
    await page.getByPlaceholder('搜索标题或内容', { exact: true }).fill('工单')
    await waitUntil(() => listCalls(state, '/tickets').at(-1)?.query.q === '工单')
    const pagination = page.locator('main').getByRole('navigation', { name: '分页', exact: true })
    assert.equal(await pagination.getByLabel('跳转页码', { exact: true }).count(), 0)
    await pagination.getByRole('button', { name: '下一页', exact: true }).click()
    await page.locator('.object-row').filter({ hasText: '工单 11' }).waitFor()
    await navigate(page, '知识 QA'); await waitList(page)
    assert.equal(await page.getByPlaceholder('搜索标题或内容', { exact: true }).inputValue(), '')
    await page.getByPlaceholder('搜索标题或内容', { exact: true }).fill('知识')
    await waitUntil(() => listCalls(state, '/qa').at(-1)?.query.q === '知识')
    await pagination.getByRole('button', { name: '跳页', exact: true }).click()
    await pagination.getByLabel('跳转页码', { exact: true }).fill('3')
    await pagination.getByRole('button', { name: '确定', exact: true }).click()
    await page.locator('.object-row').filter({ hasText: '知识 21' }).waitFor()
    await navigate(page, '服务工单')
    await page.locator('.object-row').filter({ hasText: '工单 11' }).waitFor()
    assert.equal(await page.getByPlaceholder('搜索标题或内容', { exact: true }).inputValue(), '工单')
    assert.equal(listCalls(state, '/tickets').at(-1).query.page, '2')
    await navigate(page, '知识 QA')
    await page.locator('.object-row').filter({ hasText: '知识 21' }).waitFor()
    assert.equal(await page.getByPlaceholder('搜索标题或内容', { exact: true }).inputValue(), '知识')
    assert.equal(listCalls(state, '/qa').at(-1).query.page, '3')
    await page.screenshot({ path: path.join(artifacts, '03-list-memory.png'), fullPage: true })
  })

  await scenario('04-manual-qa-requires-explicit-create', {}, async (page, state) => {
    await navigate(page, '知识 QA'); await waitList(page)
    assert.equal(await page.getByRole('combobox', { name: 'QA 来源问题', exact: true }).isVisible(), false)
    assert.equal(writes(state, /^\/qa$/).length, 0)
    await page.getByRole('button', { name: '手动新建 QA', exact: true }).click()
    const create = page.getByRole('button', { name: '新建 QA 草稿', exact: true })
    assert.ok(await create.isDisabled())
    await page.getByRole('combobox', { name: 'QA 来源问题', exact: true }).fill('报表')
    await page.getByRole('option').filter({ hasText: '报表导出问题' }).click()
    assert.equal(writes(state, /^\/qa$/).length, 0)
    await create.click()
    await page.getByRole('heading', { name: '知识内容', exact: true }).waitFor()
    assert.equal(writes(state, /^\/qa$/).length, 1)
    assert.deepEqual(writes(state, /^\/qa$/)[0].body.issue_ids, ['issue-1'])
  })

  await scenario('05-delete-confirm-undo-and-trash-restore', {}, async (page, state) => {
    await navigate(page, '服务工单'); await waitList(page)
    const firstRow = page.locator('.object-row').first()
    assert.equal(await firstRow.getByRole('button', { name: '删除', exact: true }).isVisible(), false)
    await firstRow.locator('summary').filter({ hasText: '更多操作' }).click()
    assert.equal(state.calls.filter(c => c.endpoint === '/tickets/ticket-1').length, 0, 'opening row actions must not open editor')
    await firstRow.getByRole('button', { name: '删除', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '确认删除', exact: true })
    await dialog.waitFor(); assert.equal(writes(state, /^\/records\//).length, 0)
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(writes(state, /^\/records\//).length, 0)
    await firstRow.locator('summary').filter({ hasText: '更多操作' }).click()
    await firstRow.getByRole('button', { name: '删除', exact: true }).click()
    await dialog.getByRole('button', { name: '确认删除', exact: true }).click()
    const undo = page.getByRole('button', { name: '撤销删除', exact: true })
    await undo.waitFor(); assert.equal(state.tickets[0].is_deleted, true)
    await undo.click(); await waitList(page); assert.equal(state.tickets[0].is_deleted, false)
    await firstRow.locator('summary').filter({ hasText: '更多操作' }).click()
    await firstRow.getByRole('button', { name: '删除', exact: true }).click()
    await dialog.getByRole('button', { name: '确认删除', exact: true }).click()
    await undo.waitFor()
    await expandFilters(page)
    await page.getByLabel('工单或QA记录范围', { exact: true }).selectOption('true')
    await page.getByRole('button', { name: '恢复', exact: true }).waitFor()
    assert.equal(listCalls(state, '/tickets').at(-1).query.deleted, 'true')
    await page.getByRole('button', { name: '恢复', exact: true }).click()
    await page.getByText('已恢复记录', { exact: true }).waitFor()
    assert.equal(state.tickets[0].is_deleted, false)
    await page.getByRole('button', { name: '清除筛选', exact: true }).click()
    await waitList(page)
    assert.equal(listCalls(state, '/tickets').at(-1).query.deleted, undefined)
    assert.equal(writes(state, /^\/records\//).length, 4)
  })

  await scenario('06-chat-filter-and-cancel-selection', {}, async (page, state) => {
    await openChat(page)
    assert.equal(await page.getByLabel('消息归属状态', { exact: true }).isVisible(), false)
    await expandFilters(page)
    await page.getByLabel('消息归属状态', { exact: true }).selectOption('pending')
    await waitUntil(() => listCalls(state, '/messages').at(-1)?.query.state === 'pending')
    await page.getByRole('button', { name: '清除筛选', exact: true }).click()
    await waitUntil(() => !listCalls(state, '/messages').at(-1)?.query.state)
    await page.getByRole('checkbox', { name: '选择 成员1 的消息', exact: true }).check()
    const bulk = page.locator('.assignment-bar'); await bulk.waitFor()
    assert.ok(await bulk.getByRole('button', { name: '确认归属', exact: true }).isVisible())
    assert.equal(await bulk.getByRole('button', { name: '忽略所选', exact: true }).isVisible(), false)
    assert.equal(await bulk.getByRole('button', { name: '转为待核对', exact: true }).isVisible(), false)
    await bulk.getByRole('button', { name: '取消选择', exact: true }).click()
    assert.equal(await bulk.count(), 0)
    assert.equal(writes(state, /^\/(issues|messages)/).length, 0)
    if (await filterDisclosure(page).getAttribute('open') !== null) await filterDisclosure(page).locator('summary').click()
    await page.screenshot({ path: path.join(artifacts, '06-chat-clean-actions.png'), fullPage: true })
  })

  await scenario('07-secondary-dispositions-and-busy-lock', { holdDisposition: true }, async (page, state) => {
    await openChat(page)
    const select = page.getByRole('checkbox', { name: '选择 成员1 的消息', exact: true })
    await select.check()
    await page.getByRole('checkbox', { name: '选择 成员2 的消息', exact: true }).check()
    const bulk = page.locator('.assignment-bar')
    await bulk.locator('summary').filter({ hasText: '更多处置' }).click()
    await bulk.getByLabel('忽略原因', { exact: true }).fill('人工核对确认无效')
    await bulk.getByRole('button', { name: '忽略所选', exact: true }).click()
    await waitUntil(() => state.dispositionEntered)
    assert.ok(await select.isDisabled())
    assert.ok(await page.getByPlaceholder('在此文件中搜索消息或发送人', { exact: true }).isDisabled())
    for (const name of ['取消选择', '确认归属', '忽略所选', '转为待核对']) assert.ok(await bulk.getByRole('button', { name, exact: true, includeHidden: true }).isDisabled(), `${name} must be disabled during processing`)
    assert.ok(await bulk.getByRole('combobox', { name: '聊天归属问题', exact: true, includeHidden: true }).isDisabled())
    state.releaseDisposition()
    await page.getByText('已记录忽略原因', { exact: true }).waitFor()
    assert.deepEqual(writes(state, /\/disposition$/)[0].body, { state: 'ignored', reason: '人工核对确认无效' })
    assert.deepEqual(writes(state, /\/disposition$/).map(call => [call.endpoint, JSON.parse(call.version), call.body.reason]), [
      ['/messages/message-1/disposition', '1', '人工核对确认无效'],
      ['/messages/message-2/disposition', '7', '人工核对确认无效'],
    ], 'both requests must retain the selected ids, versions and reason captured at the start')
    await select.check()
    await bulk.locator('summary').filter({ hasText: '更多处置' }).click()
    await bulk.getByRole('button', { name: '转为待核对', exact: true }).click()
    await page.getByText('已标记待人工核对，可选择问题重新归属', { exact: true }).waitFor()
    assert.equal(writes(state, /\/disposition$/).at(-1).body.state, 'needs_review')
    assert.equal(state.messages[0].raw_text, '导出报表时发生错误，请帮忙处理。')
  })

  await scenario('08-message-assignment-remains-primary', {}, async (page, state) => {
    await openChat(page)
    await page.getByRole('checkbox', { name: '选择 成员1 的消息', exact: true }).check()
    const bulk = page.locator('.assignment-bar')
    await bulk.getByPlaceholder('新问题标题', { exact: true }).fill('新导出问题')
    await bulk.getByRole('button', { name: '确认归属', exact: true }).click()
    await page.getByLabel('工单标题', { exact: true }).waitFor()
    const created = state.tickets.at(-1)
    assert.equal(await page.getByLabel('工单标题', { exact: true }).inputValue(), '新导出问题')
    assert.ok(await page.getByRole('heading', { name: created.ticket_no, exact: true }).isVisible())
    assert.equal(listCalls(state, `/tickets/${created.id}`).length, 1, 'assignment opens the exact newly created ticket')
    assert.equal(writes(state, /^\/issues$/).length, 1)
    assert.deepEqual(writes(state, /^\/issues$/)[0].body, { title: '新导出问题', messages: [{ message_id: 'message-1', relation: 'context' }] })
    assert.equal(state.messages[0].disposition, 'assigned')
    assert.equal(await bulk.count(), 0)
  })

  await scenario('09-editor-return-and-dashboard-isolation', { count: 25 }, async (page, state) => {
    await navigate(page, '服务工单'); await waitList(page)
    await page.getByPlaceholder('搜索标题或内容', { exact: true }).fill('工单')
    await waitUntil(() => listCalls(state, '/tickets').at(-1)?.query.q === '工单')
    await page.locator('main').getByRole('button', { name: '下一页', exact: true }).click()
    await page.locator('.object-row').filter({ hasText: '工单 11' }).waitFor()
    const last = page.locator('.object-row').last()
    await last.scrollIntoViewIfNeeded()
    const before = await page.evaluate(() => window.scrollY)
    await last.click()
    await page.getByLabel('工单标题', { exact: true }).waitFor()
    await page.getByRole('button', { name: '返回工单列表', exact: true }).click()
    await page.locator('.object-row').filter({ hasText: '工单 20' }).waitFor()
    assert.equal(await page.getByPlaceholder('搜索标题或内容', { exact: true }).inputValue(), '工单')
    assert.ok(Math.abs(await page.evaluate(() => window.scrollY) - before) < 3, 'return must restore list scroll position')
    await page.locator('.sidebar nav').getByRole('button', { name: '工作台', exact: true }).click()
    await page.getByRole('heading', { name: '最近的服务记录', exact: true }).waitFor()
    await page.locator('.record-row').filter({ hasText: '工单 01' }).waitFor()
    assert.equal(listCalls(state, '/tickets').at(-1).query.page_size, '6')
    assert.equal(listCalls(state, '/tickets').at(-1).query.q, undefined, 'dashboard must not inherit a list search')
    assert.equal(listCalls(state, '/tickets').at(-1).query.deleted, undefined)
    await navigate(page, '服务工单')
    await page.locator('.object-row').filter({ hasText: '工单 11' }).waitFor()
    assert.equal(listCalls(state, '/tickets').at(-1).query.page, '2')
    assert.equal(listCalls(state, '/tickets').at(-1).query.q, '工单')
  })

  await scenario('10-select-page-and-partial-selection', {}, async (page, state) => {
    await openChat(page)
    const all = page.getByRole('checkbox', { name: '选择本页消息', exact: true })
    await all.check()
    assert.equal(await page.locator('.message-row input:checked').count(), 2)
    await page.locator('.assignment-bar').getByText('已选 2 条', { exact: true }).waitFor()
    await page.getByRole('checkbox', { name: '选择 成员1 的消息', exact: true }).uncheck()
    assert.ok(await all.evaluate(element => element.indeterminate))
    await page.locator('.assignment-bar').getByRole('button', { name: '取消选择', exact: true }).click()
    assert.equal(await page.locator('.message-row input:checked').count(), 0)
    assert.equal(await all.isChecked(), false)
    assert.equal(await all.evaluate(element => element.indeterminate), false)
    assert.equal(writes(state, /^\/(issues|messages)/).length, 0)
  })

  await scenario('11-menu-keyboard-outside-and-row-isolation', {}, async (page, state) => {
    await navigate(page, '服务工单'); await waitList(page)
    const row = page.locator('.object-row').first(), menu = row.locator('details.more-actions'), trigger = menu.locator('summary')
    await trigger.focus(); await trigger.press('Enter')
    const remove = menu.getByRole('button', { name: '删除', exact: true })
    await remove.focus(); await remove.press('Escape')
    assert.equal(await menu.getAttribute('open'), null)
    assert.ok(await trigger.evaluate(element => element === document.activeElement), 'Escape must return focus to the menu trigger')
    await trigger.click(); await page.getByRole('heading', { name: '服务工单', exact: true }).click()
    assert.equal(await menu.getAttribute('open'), null, 'outside pointer must close actions')
    await trigger.click(); await remove.click()
    await page.getByRole('dialog', { name: '确认删除', exact: true }).waitFor()
    assert.equal(state.calls.filter(call => call.endpoint === '/tickets/ticket-1').length, 0, 'delete action must never trigger the row editor')
    await page.getByRole('dialog', { name: '确认删除', exact: true }).getByRole('button', { name: '取消', exact: true }).click()
    const filters = await expandFilters(page), filterTrigger = filters.locator('summary')
    await page.getByLabel('工单或QA记录范围', { exact: true }).focus()
    await page.keyboard.press('Escape')
    assert.equal(await filters.getAttribute('open'), null)
    assert.ok(await filterTrigger.evaluate(element => element === document.activeElement))
    await filterTrigger.click(); await page.getByRole('heading', { name: '服务工单', exact: true }).click()
    assert.equal(await filters.getAttribute('open'), null)
  })

  await scenario('12-search-debounce-locks-stale-selection', { holdSearch: true }, async (page, state) => {
    await openChat(page)
    await page.getByRole('checkbox', { name: '选择 成员1 的消息', exact: true }).check()
    const lockedAtInput = await page.getByPlaceholder('在此文件中搜索消息或发送人', { exact: true }).evaluate(async element => {
      element.value = '更新'; element.dispatchEvent(new Event('input', { bubbles: true }))
      await Promise.resolve()
      return {
        disabled: [...document.querySelectorAll('.message-table input[type="checkbox"]')].every(input => input.disabled),
        selected: document.querySelectorAll('.message-row input:checked').length,
        rows: document.querySelectorAll('.message-row').length,
      }
    })
    assert.deepEqual(lockedAtInput, { disabled: true, selected: 0, rows: 2 }, 'search input must immediately disable stale rows and clear selection before debounce completes')
    await waitUntil(() => state.searchEntered)
    assert.ok(await page.getByRole('checkbox', { name: '选择本页消息', exact: true }).isDisabled())
    assert.ok(await page.getByRole('checkbox', { name: '选择 成员1 的消息', exact: true }).isDisabled())
    state.releaseSearch()
    await page.locator('.message-row').filter({ hasText: '请更新客户端再重试。' }).waitFor()
    await page.waitForFunction(() => document.querySelectorAll('.message-row').length === 1 && !document.querySelector('.message-row input').disabled)
    assert.equal(await page.getByRole('checkbox', { name: '选择 成员1 的消息', exact: true }).count(), 0)
    assert.ok(await page.getByRole('checkbox', { name: '选择 成员2 的消息', exact: true }).isEnabled())
    assert.equal(writes(state, /^\/(issues|messages)/).length, 0)
  })

  await scenario('13-mobile-menu-layout', { viewport: { width: 375, height: 812 } }, async page => {
    await navigate(page, '服务工单'); await waitList(page)
    assert.equal(await page.locator('.sidebar').isVisible(), false, 'navigation closes after selecting a destination')
    await openNavigation(page)
    const tools = page.locator('.sidebar details').filter({ hasText: '工具与设置' })
    await tools.locator('summary svg').click()
    assert.ok(await page.locator('.sidebar nav').getByRole('button', { name: 'AI 任务', exact: true }).isVisible(), 'mobile tools icon must toggle its section')
    await page.getByRole('button', { name: '关闭导航', exact: true }).click()
    await page.locator('.sidebar').waitFor({ state: 'hidden' })
    const menu = page.locator('.object-row').first().locator('details.more-actions')
    await menu.locator('summary').click()
    const actionBox = await menu.locator('.more-actions__items').boundingBox()
    assert.ok(actionBox.x >= 0 && actionBox.x + actionBox.width <= 375, 'mobile action menu must fit inside viewport')
    await page.screenshot({ path: path.join(artifacts, '13-mobile-actions.png'), fullPage: true })
    const filters = await expandFilters(page), filterBox = await filters.locator('.more-actions__items').boundingBox()
    assert.ok(filterBox.x >= 0 && filterBox.x + filterBox.width <= 375, 'mobile filter menu must fit inside viewport')
    await page.screenshot({ path: path.join(artifacts, '13-mobile-filters.png'), fullPage: true })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'mobile page must not overflow horizontally')
  })

  await scenario('14-open-detail-before-search-debounce', { count: 25 }, async (page, state) => {
    await navigate(page, '服务工单'); await waitList(page)
    await page.getByPlaceholder('搜索标题或内容', { exact: true }).evaluate(element => {
      element.value = '1'; element.dispatchEvent(new Event('input', { bubbles: true }))
      document.querySelector('.object-row').click()
    })
    await page.getByLabel('工单标题', { exact: true }).waitFor()
    await waitUntil(() => listCalls(state, '/tickets').some(call => call.query.q === '1'))
    assert.ok(await page.getByLabel('工单标题', { exact: true }).isVisible(), 'the deferred list request must complete while the editor remains open')
    assert.ok(state.calls.findIndex(call => call.endpoint === '/tickets/ticket-1') < state.calls.findIndex(call => call.endpoint === '/tickets' && call.query.q === '1'), 'the editor must open before the queued search request')
    await page.getByRole('button', { name: '返回工单列表', exact: true }).click()
    await waitList(page)
    assert.equal(await page.getByPlaceholder('搜索标题或内容', { exact: true }).inputValue(), '1')
    const pagination = page.locator('main').getByRole('navigation', { name: '分页', exact: true })
    assert.match(await pagination.innerText(), /共 12 条/)
    const next = pagination.getByRole('button', { name: '下一页', exact: true })
    assert.ok(await next.isEnabled(), 'returning after the queued search must not leave pagination permanently busy')
    const menu = page.locator('.object-row').first().locator('details.more-actions')
    assert.equal(await menu.locator('summary').getAttribute('aria-disabled'), 'false')
    await menu.locator('summary').click()
    assert.ok(await menu.getByRole('button', { name: '删除', exact: true }).isVisible())
    await next.click()
    await page.locator('.object-row').filter({ hasText: '工单 19' }).waitFor()
    assert.equal(await page.locator('.object-row').count(), 2)
    assert.equal(listCalls(state, '/tickets').at(-1).query.q, '1')
    assert.equal(listCalls(state, '/tickets').at(-1).query.page, '2')
  })
} finally {
  await writeFile(path.join(artifacts, 'results.json'), JSON.stringify(results, null, 2))
  await browser.close()
}
if (results.some(result => !result.passed)) process.exitCode = 1
console.log(`${results.filter(result => result.passed).length}/${results.length} navigation scenarios passed`)
