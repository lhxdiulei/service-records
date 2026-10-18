// Responsive regression against synthetic API fixtures ONLY.
// All /api/ calls are intercepted; every non-GET API request is rejected.
// Screenshots are explicitly watermarked: these are not localhost:8088 business data.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { loadChromium } from './browser-utils.mjs'
const chromium = await loadChromium()
const baseURL = process.env.MOBILE_BROWSER_URL || 'http://127.0.0.1:5173'
const origin = new URL(baseURL).origin
assert.notEqual(new URL(baseURL).port, '8088', 'Run against the source-copy dev server, not the deployed site')
const artifacts = fileURLToPath(new URL('../test-results/mobile/', import.meta.url))
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
const widths = (process.env.MOBILE_WIDTHS || '360,390,430,1440').split(',').map(Number)
const results = []
const stamp = '2026-10-18T09:15:00+08:00'
const longToken = 'customer-report-export-investigation-evidence-'.repeat(5)
const longURL = `https://example.invalid/support/${longToken}?context=${'A9'.repeat(80)}`
const filename = `移动端合成回归_${longToken}_跨日服务沟通记录与证据.txt`
const question = `客户反馈导出时出现错误，请核对全部上下文。\n${longURL}\n保留原始空格、标点与表情 😀。`
const answer = `客服建议重试并确认导出范围，当前等待客户回复。\n${longURL}\n${'这是需要完整保留并可以阅读的原文。'.repeat(12)}`
const title = `移动端合成样例：跨日导出问题与长编号 ${longToken}`
const issueLabel = `导出问题 ${longToken}`

function fixture(options = {}) {
  const state = { calls: [], rejectedWrites: [], unexpected: [], pageErrors: [] }
  const modalGate = options.delayModal ? new Promise(resolve => { state.releaseModal = resolve }) : null
  const user = { id: 'mobile-user', username: 'mobile-fixture', display_name: '合成测试管理员', role: 'admin', version: 1, created_at: stamp, last_login_at: stamp }
  const participants = [{ id: 'customer', display_name: '客户姓名与团队' }, { id: 'agent', display_name: '客服测试员' }]
  const messages = [question, answer, '收到，稍等确认。'].map((raw, i) => ({
    id: `message-${i + 1}`, raw_text: raw, body_text: raw, sender_name_raw: i === 1 ? '客服测试员' : '客户姓名与团队',
    sender_participant_id: i === 1 ? 'agent' : 'customer', sender_role: i === 1 ? 'support' : 'customer',
    direct_body_spans: [{ start_cp: 0, end_cp: Array.from(raw).length }], kind: 'text', sent_at: stamp,
    relation: i === 0 ? 'question' : i === 1 ? 'answer' : 'context', source_filename: filename, is_deleted: false,
    disposition: i === 0 ? 'pending' : 'assigned', disposition_version: 1,
    assigned_issues: i ? [{ issue_id: 'issue-1', label: issueLabel }] : [],
  }))
  const evidence = [{ evidence_span_id: 'evidence-1', message_id: 'message-1', start_cp: 0, end_cp: 10, excerpt: Array.from(question).slice(0, 10).join(''), field_key: 'problem', relation: 'supports' }]
  function object(kind) {
    const id = `${kind}-1`
    const revision = { id: `${kind}-revision-2`, revision_no: 2, state: kind === 'ticket' ? 'in_review' : 'draft', state_version: 1,
      created_by: user.id, origin: 'ai', stale: false, title, question: title, answer,
      problem_text: question, impact_text: '影响日常报表交付', handling_summary: answer, current_conclusion: '等待客户确认', status: 'waiting_customer',
      answer_state: 'supported', applicability: `适用于 ${longURL}`, claims: [], answer_claims: [], next_actions: [], contributors: [],
      first_visible_message_id: 'message-1', first_question_message_id: 'message-1', date_basis: 'first_question', start_context_complete: true,
      evidence: kind === 'ticket' ? evidence : evidence.map(e => ({ ...e, field_key: 'question' })), issue_ids: ['issue-1'],
    }
    return { id, ticket_no: kind === 'ticket' ? 'TK-MOBILE-SYNTHETIC-001' : undefined, qa_no: kind === 'qa' ? 'QA-MOBILE-SYNTHETIC-001' : undefined,
      issue_id: 'issue-1', version: 1, delete_version: 0, current_revision_id: null, is_deleted: false, updated_at: stamp,
      source_filenames: [filename], latest_revision: revision }
  }
  const ticket = object('ticket'), qa = object('qa')
  const summary = { version: 1, total: 3, retained: 3, filtered: 0, restored: 0, reasons: [] }
  const batch = { id: 'batch-1', original_filename: filename, source_encoding: 'utf-8', message_count: 3,
    message_counts: { active: 3, deleted: 0, pending: 1, needs_review: 0 }, confirmed_at: stamp, created_at: stamp,
    version: 2, parse_version: 1, is_deleted: false, screening_summary: summary }
  const job = { id: 'job-mobile-synthetic', batch_id: 'batch-1', mode: 'both', model_profile_snapshot: { id: 'local' }, state: 'succeeded',
    version: 1, created_at: stamp, checkpoint: { messages_done: 3, messages_total: 3, extraction_done: 1, extraction_total: 1, topic_batches: 1, needs_review_messages: 0 } }
  const records = [ticket, qa].map((o, i) => ({ record_kind: i ? 'qa' : 'ticket', record_id: o.id, revision_id: o.latest_revision.id,
    revision_no: 2, record_no: o.ticket_no || o.qa_no, title, state: o.latest_revision.state, action: 'created', is_deleted: false }))
  const accounts = [user, { ...user, id: 'user-2', username: `reviewer-${longToken}`, display_name: '需要核对长用户名的审核员', role: 'reviewer' }]
  const paginate = (items, url) => { const page = Number(url.searchParams.get('page') || 1), size = Number(url.searchParams.get('page_size') || 10); return { items: items.slice((page - 1) * size, page * size), total: items.length, page, page_size: size } }
  const detail = o => ({ object: o, revisions: [o.latest_revision, { ...o.latest_revision, id: `${o.id.split('-')[0]}-revision-1`, revision_no: 1, state: 'superseded' }], source_messages: messages, participants,
    reviews: [{ id: 'review-1', action: 'submit', reason: `请核对原文：${longURL}`, created_at: stamp, actor_name: '合成审核员', actor_username: `reviewer-${longToken}`, revision_id: o.latest_revision.id, revision_no: 2 }],
    notes: [{ id: 'note-1', body: `合成内部备注：${longURL}`, author_name: '合成客服', created_at: stamp }], events: [] })
  async function route(route) {
    const request = route.request(), url = new URL(request.url()), method = request.method()
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === origin) return route.continue()
      state.unexpected.push(`external ${request.url()}`)
      return route.abort()
    }
    const endpoint = url.pathname.replace('/api/v1', '')
    state.calls.push({ endpoint, method, query: Object.fromEntries(url.searchParams) })
    const respond = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (method !== 'GET') {
      state.rejectedWrites.push(`${method} ${endpoint}`)
      return respond({ detail: { code: 'synthetic_read_only', message: '移动端合成测试禁止业务写入' } }, 405)
    }
    if (endpoint === '/auth/csrf') return respond({ csrf_token: 'synthetic-only' })
    if (endpoint === '/auth/me') return respond(user)
    if (endpoint === '/overview') return respond({ tickets: 1, official_tickets: 0, qa: 1, official_qa: 0, reviews: 1, unassigned_messages: 1 })
    if (endpoint === '/issues') return respond([{ id: 'issue-1', label: issueLabel, lifecycle: 'active', version: 1, created_at: stamp }])
    if (endpoint === '/integrations/dify') return respond([{ id: 'local', configured: true }, { id: 'external', configured: false }])
    if (endpoint === '/imports') return respond(paginate([batch], url))
    if (endpoint === '/imports/batch-1') return respond(batch)
    if (endpoint === '/imports/batch-1/preview') {
      if (options.delayModal === 'preview') await modalGate
      return respond({ batch, records: messages.map((m, i) => ({ ...m, message_id: m.id, sender: m.sender_name_raw, source_index: i, source_line_start: i * 4 + 1, source_line_end: i * 4 + 4 })), total: 3, page: 1, page_size: 10, warnings: [], screening_summary: summary })
    }
    if (endpoint === '/messages') return respond(paginate(messages.filter(m => !url.searchParams.get('state') || m.disposition === url.searchParams.get('state')), url))
    if (endpoint === '/tickets') return respond(paginate([ticket], url))
    if (endpoint === '/qa') return respond(paginate([qa], url))
    if (endpoint === '/tickets/ticket-1') return respond(detail(ticket))
    if (endpoint === '/qa/qa-1') return respond(detail(qa))
    if (endpoint === '/reviews') return respond(paginate([{ ...ticket, objectKind: 'ticket' }], url))
    if (endpoint === '/jobs') return respond(paginate([job], url))
    if (endpoint === `/jobs/${job.id}/records`) {
      if (options.delayModal === 'results') await modalGate
      return respond(paginate(records, url))
    }
    if (endpoint === '/users') return respond(paginate(accounts, url))
    if (endpoint.startsWith('/users/')) return respond(accounts.find(a => a.id === endpoint.split('/').at(-1)))
    state.unexpected.push(`${method} ${endpoint}`)
    return respond({ detail: { code: 'unexpected_request', message: '未预期的合成测试读取' } }, 500)
  }
  return { state, route }
}

async function settle(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))) }
async function noOverflow(page, label) {
  await settle(page)
  const size = await page.evaluate(() => ({ viewport: innerWidth, html: document.documentElement.scrollWidth, body: document.body.scrollWidth,
    offenders: [...document.querySelectorAll('main *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed' }).slice(0, 12).map(e => ({ tag: e.tagName, class: e.className, right: Math.round(e.getBoundingClientRect().right) })) }))
  assert.ok(size.html <= size.viewport + 1 && size.body <= size.viewport + 1, `${label}: document overflow ${JSON.stringify(size)}`)
}
async function withinViewport(locator, label, minimumHeight = 0) {
  await locator.scrollIntoViewIfNeeded(); const rect = await locator.boundingBox(), page = locator.page(), viewport = page.viewportSize()
  assert.ok(rect && rect.x >= -1 && rect.x + rect.width <= viewport.width + 1 && rect.y >= -1 && rect.y + rect.height <= viewport.height + 1, `${label} must be reachable inside viewport: ${JSON.stringify(rect)}`)
  if (minimumHeight) assert.ok(rect.height >= minimumHeight - 1, `${label} needs ${minimumHeight}px touch height, got ${rect.height}`)
  assert.ok(await locator.evaluate(element => { const r = element.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return !!hit && (element === hit || element.contains(hit)) }), `${label} center must not be covered by another surface`)
}
async function hasFocus(locator, label) {
  const page = locator.page()
  await page.waitForFunction(element => element === document.activeElement, await locator.elementHandle(), { timeout: 1200 }).catch(async () => {
    throw new Error(`${label}: active=${await page.evaluate(() => document.activeElement?.outerHTML.slice(0, 400))}`)
  })
}
async function screenshot(page, name) {
  await page.evaluate(() => {
    let mark = document.getElementById('synthetic-test-watermark')
    if (!mark) { mark = document.createElement('div'); mark.id = 'synthetic-test-watermark'; document.body.append(mark) }
    mark.textContent = `合成数据 UI 回归 · ${innerWidth}px · 非 8088 现场`
    Object.assign(mark.style, { position: 'fixed', bottom: '0', right: '0', zIndex: '2147483647', color: '#fff', background: '#172a3a', font: '10px/1.5 sans-serif', padding: '2px 6px', pointerEvents: 'none', maxWidth: '100vw' })
  })
  const output = path.join(artifacts, `${name}.png`)
  await page.screenshot({ path: output, fullPage: false, animations: 'disabled' })
  await page.screenshot({ path: path.join(artifacts, `${name}-full.png`), fullPage: true, animations: 'disabled' })
  return output
}
async function openNavigation(page) {
  const toggle = page.locator('.mobile-nav-toggle')
  if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
}
async function navigate(page, label) {
  await openNavigation(page)
  if (['AI 任务', '设置'].includes(label)) {
    const details = page.locator('.secondary-navigation')
    if (await details.getAttribute('open') === null) await details.locator('summary').click()
  }
  await page.locator('#workspace-navigation').getByRole('button', { name: new RegExp(`^${label}(?:\\s*\\d+)?$`) }).click()
  if (label !== '工作台') await page.getByRole('heading', { name: label === '设置' ? '系统设置' : label, exact: true }).waitFor()
  if (page.viewportSize().width < 768) assert.equal(await page.locator('.mobile-nav-toggle').getAttribute('aria-expanded'), 'false')
}
async function filters(page) {
  const detail = page.locator('main details.list-filters').first()
  if (await detail.getAttribute('open') === null) await detail.locator('summary').click()
  return detail
}
async function scenario(width, name, run, options = {}) {
  if (process.env.MOBILE_SCENARIOS && !process.env.MOBILE_SCENARIOS.split(',').includes(name)) return
  const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 1080 }, locale: 'zh-CN', serviceWorkers: 'block', hasTouch: width < 768 })
  const { state, route } = fixture(options)
  await context.route('**/*', route)
  const page = await context.newPage(); page.setDefaultTimeout(9000)
  page.on('pageerror', error => state.pageErrors.push(error.message))
  const id = `${width}-${name}`
  try {
    await page.goto(baseURL); await page.getByRole('heading', { name: '把每一次沟通，整理清楚。', exact: true }).waitFor()
    await run(page, width, state)
    assert.deepEqual(state.unexpected, [], 'No unhandled or external requests')
    assert.deepEqual(state.rejectedWrites, [], 'UI traversal must not request business writes')
    assert.deepEqual(state.pageErrors, [], 'No browser runtime errors')
    results.push({ name: id, passed: true, apiReads: state.calls.length, apiWrites: 0 }); console.log(`PASS ${id}`)
  } catch (error) {
    const output = await screenshot(page, `${id}-failure`).catch(() => null)
    results.push({ name: id, passed: false, error: error.stack || String(error), screenshot: output, unexpected: state.unexpected, rejectedWrites: state.rejectedWrites, pageErrors: state.pageErrors })
    console.error(`FAIL ${id}: ${error.message}`)
  } finally { state.releaseModal?.(); await context.close() }
}

try {
  for (const width of widths) {
    await scenario(width, 'navigation-dashboard', async page => {
      await noOverflow(page, 'dashboard')
      await screenshot(page, `${width}-01-dashboard`)
      const toggle = page.locator('.mobile-nav-toggle'), nav = page.locator('#workspace-navigation')
      if (width < 768) {
        await withinViewport(toggle, 'navigation toggle', 44)
        assert.equal(await toggle.getAttribute('aria-expanded'), 'false')
        await toggle.click(); await settle(page)
        assert.equal(await toggle.getAttribute('aria-expanded'), 'true')
        await page.waitForFunction(() => document.querySelector('#workspace-navigation')?.contains(document.activeElement), null, { timeout: 1500 }).catch(async () => {
          throw new Error(`opening drawer moves focus into navigation: ${JSON.stringify(await page.evaluate(() => ({ active: document.activeElement?.outerHTML.slice(0, 300), close: document.querySelector('.mobile-nav-close')?.outerHTML.slice(0, 300), closeStyle: document.querySelector('.mobile-nav-close') && { display: getComputedStyle(document.querySelector('.mobile-nav-close')).display, visibility: getComputedStyle(document.querySelector('.mobile-nav-close')).visibility }, inert: document.querySelector('#workspace-navigation')?.inert })))}`)
        })
        await withinViewport(nav.getByRole('button', { name: '关闭导航', exact: true }), 'drawer close', 44)
        await noOverflow(page, 'open navigation'); await screenshot(page, `${width}-02-navigation`)
        await page.keyboard.press('Shift+Tab')
        assert.ok(await nav.evaluate(e => e.contains(document.activeElement)), 'backward Tab stays inside drawer')
        await page.keyboard.press('Tab')
        assert.ok(await nav.evaluate(e => e.contains(document.activeElement)), 'forward Tab stays inside drawer')
        await page.keyboard.press('Escape')
        assert.equal(await toggle.getAttribute('aria-expanded'), 'false')
        assert.ok(await toggle.evaluate(e => e === document.activeElement), 'Escape restores trigger focus')
        await toggle.click()
        const backdrop = page.locator('.mobile-nav-backdrop'), box = await backdrop.boundingBox()
        await backdrop.click({ position: { x: box.width - 4, y: box.height / 2 } })
        assert.equal(await toggle.getAttribute('aria-expanded'), 'false')
        assert.ok(await toggle.evaluate(e => e === document.activeElement), 'backdrop close restores trigger focus')
      } else {
        assert.equal(await toggle.isVisible(), false, 'desktop keeps sidebar and hides mobile toggle')
        assert.ok(await nav.isVisible())
      }
      await navigate(page, '服务工单')
      await page.locator('.object-row').waitFor(); await noOverflow(page, 'navigation destination')
      if (width < 768) assert.ok(await page.locator('main').evaluate(e => e === document.activeElement || e.contains(document.activeElement)), 'navigation sends focus to main content')
    })

    await scenario(width, 'files-import-dialog', async page => {
      await navigate(page, '聊天记录'); await page.locator('.import-file-row').waitFor()
      await noOverflow(page, 'file library with long filename')
      await filters(page); await withinViewport(page.getByLabel('文件导入状态', { exact: true }), 'file status filter', width < 768 ? 44 : 0)
      await noOverflow(page, 'expanded file filters')
      await page.keyboard.press('Escape')
      const actions = page.locator('.import-file-row .more-actions').first()
      await actions.locator('summary').click()
      await withinViewport(actions.locator('.more-actions__items'), 'file action menu')
      await page.keyboard.press('Escape')
      assert.equal(await actions.getAttribute('open'), null, 'Escape closes row action menu')
      await actions.locator('summary').click()
      await page.getByRole('heading', { name: '聊天记录', exact: true }).click()
      assert.equal(await actions.getAttribute('open'), null, 'outside press closes row action menu')
      await screenshot(page, `${width}-03-file-library`)
      await page.getByRole('button', { name: '查看导入结果', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '导入结果', exact: true }); await dialog.waitFor()
      await noOverflow(page, 'long import preview')
      assert.equal(await dialog.locator('pre').first().textContent(), question)
      await withinViewport(dialog.getByRole('button', { name: '查看文件聊天', exact: true }), 'import bottom action', width < 768 ? 44 : 0)
      await screenshot(page, `${width}-04-import-dialog`)
      await dialog.getByRole('button', { name: '关闭', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
      await page.getByRole('button', { name: '查看导入结果', exact: true }).click()
      await dialog.getByRole('button', { name: '关闭导入预览', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
      const opener = page.getByRole('button', { name: '查看导入结果', exact: true })
      await opener.click(); await dialog.waitFor()
      await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
      await hasFocus(opener, 'import Escape restores opener focus')
    })

    if (width < 768) for (const modal of ['preview', 'results']) await scenario(width, `async-${modal}-dialog-navigation`, async (page, viewportWidth, state) => {
      await navigate(page, modal === 'preview' ? '聊天记录' : 'AI 任务')
      if (modal === 'results') await page.locator('summary').filter({ hasText: '对已有问题重新生成' }).click()
      const opener = page.getByRole('button', { name: modal === 'preview' ? '查看导入结果' : '查看生成记录', exact: true })
      await opener.waitFor()
      const originalOverflow = await page.evaluate(() => document.body.style.overflow)
      const responsePath = modal === 'preview' ? '/api/v1/imports/batch-1/preview' : '/api/v1/jobs/job-mobile-synthetic/records'
      const pending = page.waitForRequest(request => new URL(request.url()).pathname === responsePath && request.method() === 'GET')
      await opener.click(); await pending
      const dialog = page.getByRole('dialog', { name: modal === 'preview' ? '导入结果' : '任务生成记录', exact: true })
      assert.equal(await dialog.count(), 0, 'modal remains closed while its synthetic GET is held')
      await openNavigation(page)
      const nav = page.locator('#workspace-navigation')
      await page.waitForFunction(() => document.querySelector('#workspace-navigation')?.contains(document.activeElement))
      assert.equal(await page.locator('.mobile-nav-toggle').getAttribute('aria-expanded'), 'true')
      assert.equal(await page.evaluate(() => document.body.style.overflow), 'hidden', 'drawer locks background scrolling')
      state.releaseModal()
      await dialog.waitFor()
      await page.waitForFunction(element => element.contains(document.activeElement), await dialog.elementHandle())
      assert.equal(await page.locator('.mobile-nav-toggle').getAttribute('aria-expanded'), 'false', 'arriving dialog closes the drawer')
      assert.equal(await nav.getAttribute('aria-hidden'), 'true')
      assert.equal(await page.locator('.mobile-nav-backdrop').count(), 0, 'no stale navigation backdrop remains')
      assert.equal(await page.evaluate(() => document.body.style.overflow), 'hidden', 'dialog retains the scroll lock')
      await noOverflow(page, `async ${modal} overlay`)
      await screenshot(page, `${viewportWidth}-async-${modal}-dialog`)
      await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
      await page.waitForFunction(() => {
        const active = document.activeElement
        return active !== document.body && active?.getClientRects().length && !active.closest('[inert]') && !active.matches(':disabled') && getComputedStyle(active).visibility !== 'hidden'
      })
      assert.equal(await page.evaluate(() => document.body.style.overflow), originalOverflow, 'closing final overlay restores original body overflow')
      assert.equal(await page.locator('.main-shell').getAttribute('inert'), null, 'main content becomes interactive again')
      await page.evaluate(() => window.scrollTo(0, 0))
      const scrollable = await page.evaluate(() => document.documentElement.scrollHeight > innerHeight)
      if (scrollable) {
        await page.mouse.move(viewportWidth - 12, page.viewportSize().height / 2)
        await page.mouse.wheel(0, 180)
        await page.waitForFunction(() => window.scrollY > 0)
      }
      await openNavigation(page)
      await page.getByRole('button', { name: '关闭导航', exact: true }).click()
      await hasFocus(page.locator('.mobile-nav-toggle'), 'navigation still works after async modal race')
    }, { delayModal: modal })

    await scenario(width, 'chat-assignment', async page => {
      await navigate(page, '聊天记录'); await page.getByRole('button', { name: '打开文件', exact: true }).click()
      await page.locator('.message-row').first().waitFor()
      assert.equal(await page.locator('.message-row pre').first().textContent(), question)
      await noOverflow(page, 'chat and long filename')
      await filters(page); await withinViewport(page.getByLabel('消息归属状态', { exact: true }), 'chat filter')
      await page.keyboard.press('Escape')
      await page.getByLabel('选择 客户姓名与团队 的消息', { exact: true }).first().check()
      await page.getByPlaceholder('新问题标题', { exact: true }).fill(`合成表单输入 ${longToken}`)
      await withinViewport(page.getByRole('button', { name: '确认归属', exact: true }), 'assignment action', width < 768 ? 44 : 0)
      await noOverflow(page, 'assignment fields')
      await page.getByRole('combobox', { name: '聊天归属问题', exact: true }).fill('导出问题')
      await withinViewport(page.locator('.search-select__panel'), 'assignment searchable popup')
      await page.getByRole('option').filter({ hasText: issueLabel }).click()
      await screenshot(page, `${width}-05-chat-assignment`)
      await page.getByRole('button', { name: '取消选择', exact: true }).click()
      assert.equal(await page.locator('.assignment-bar').count(), 0)
      await page.getByRole('button', { name: '返回文件列表', exact: true }).click()
      await page.locator('.import-file-row').waitFor()
    })

    for (const kind of ['ticket', 'qa']) await scenario(width, `${kind}-editor-evidence`, async page => {
      await navigate(page, kind === 'ticket' ? '服务工单' : '知识 QA'); await page.locator('.object-row').first().waitFor()
      await noOverflow(page, `${kind} list`)
      await filters(page); await noOverflow(page, `${kind} filters`); await page.keyboard.press('Escape')
      await screenshot(page, `${width}-${kind}-list`)
      await page.locator('.object-row').first().click()
      await page.getByRole('heading', { name: kind === 'ticket' ? '工单内容' : '知识内容', exact: true }).waitFor()
      await noOverflow(page, `${kind} detail`)
      await withinViewport(page.getByRole('combobox', { name: '记录版本', exact: true }), 'version switch', width < 768 ? 44 : 0)
      await page.getByRole('combobox', { name: '记录版本', exact: true }).selectOption(`${kind}-revision-1`)
      await page.getByRole('combobox', { name: '记录版本', exact: true }).selectOption(`${kind}-revision-2`)
      const source = page.locator('[data-evidence-raw="message-1"]')
      assert.equal(await source.textContent(), question, 'long original text is retained exactly')
      await page.getByLabel('搜索来源聊天', { exact: true }).fill('客户反馈')
      assert.equal(await page.locator('[data-evidence-raw]').count(), 1)
      await noOverflow(page, `${kind} filtered source`)
      await screenshot(page, `${width}-${kind}-evidence`)
      await page.getByLabel('搜索来源聊天', { exact: true }).fill('')
      await page.locator('summary').filter({ hasText: '手动粘贴原文' }).click()
      await page.getByRole('combobox', { name: '手动引用的来源聊天', exact: true }).fill('客户反馈')
      await withinViewport(page.locator('.search-select__panel'), 'source searchable popup')
      await page.keyboard.press('Escape')
      const field = kind === 'ticket' ? page.getByLabel('工单标题', { exact: true }) : page.getByLabel('问题', { exact: true })
      await withinViewport(field, `${kind} main form`)
      const original = await field.inputValue(); await field.fill(`${original} 合成编辑`)
      assert.match(await field.inputValue(), /合成编辑$/)
      await noOverflow(page, `${kind} edited form`)
      const comment = page.getByLabel('审核意见 / 内部备注', { exact: true })
      await comment.fill(`合成意见 ${longURL}`); await withinViewport(comment, 'review comment')
      const action = kind === 'ticket' ? page.getByRole('button', { name: '保存内部备注', exact: true }) : page.getByRole('button', { name: '保存并提交审核', exact: true })
      await withinViewport(action, 'editor action', width < 768 ? 44 : 0)
      await noOverflow(page, `${kind} review history`)
      await screenshot(page, `${width}-${kind}-review`)
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('button', { name: kind === 'ticket' ? '返回工单列表' : '返回知识列表', exact: true }).click()
      await page.locator('.object-row').first().waitFor()
    })

    await scenario(width, 'reviews-actions', async page => {
      await navigate(page, '审核中心'); await page.locator('.review-row').waitFor(); await noOverflow(page, 'review list')
      await screenshot(page, `${width}-06-review-list`)
      await page.getByRole('button', { name: '查看与审核', exact: true }).click()
      await page.getByRole('heading', { name: '审核与处理记录', exact: true }).waitFor()
      await withinViewport(page.getByRole('button', { name: '批准此版本', exact: true }), 'approve action', width < 768 ? 44 : 0)
      await withinViewport(page.getByRole('button', { name: '驳回', exact: true }), 'reject action', width < 768 ? 44 : 0)
      await noOverflow(page, 'review bottom actions')
      await screenshot(page, `${width}-07-review-actions`)
      await page.getByRole('button', { name: '返回审核列表', exact: true }).click(); await page.locator('.review-row').waitFor()
    })

    await scenario(width, 'ai-task-results', async page => {
      await navigate(page, 'AI 任务'); await page.locator('.job-row').waitFor()
      await page.locator('summary').filter({ hasText: '对已有问题重新生成' }).click()
      await withinViewport(page.getByRole('combobox', { name: 'AI 抽取问题', exact: true }), 'AI issue picker')
      await noOverflow(page, 'AI configuration and progress'); await screenshot(page, `${width}-08-ai-tasks`)
      await page.getByRole('button', { name: '查看生成记录', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '任务生成记录', exact: true }); await dialog.waitFor()
      await noOverflow(page, 'AI generated record dialog')
      await withinViewport(dialog.getByRole('button', { name: '查看此版本', exact: true }).last(), 'last result action', width < 768 ? 44 : 0)
      await screenshot(page, `${width}-09-ai-results`)
      await dialog.getByRole('button', { name: '关闭', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
    })

    await scenario(width, 'settings-form-dialog', async page => {
      await navigate(page, '设置'); await page.getByRole('button', { name: '新增账号', exact: true }).waitFor()
      await page.getByLabel('搜索账号', { exact: true }).fill('合成'); await page.getByLabel('搜索账号', { exact: true }).fill('')
      await page.waitForFunction(() => !document.querySelector('.user-management button.primary')?.disabled)
      await page.getByRole('heading', { name: '系统设置', exact: true }).click()
      await noOverflow(page, 'settings long usernames'); await screenshot(page, `${width}-10-settings`)
      if (width < 768) assert.ok(await page.locator('.user-table-scroll').evaluate(e => e.scrollWidth <= e.clientWidth + 1), 'mobile user cards must not need horizontal table scrolling')
      const create = page.getByRole('button', { name: '新增账号', exact: true }); await create.click()
      const dialog = page.getByRole('dialog', { name: '新增账号', exact: true }); await dialog.waitFor()
      await dialog.getByLabel('用户名', { exact: true }).fill('synthetic-mobile-only')
      await dialog.getByLabel('显示姓名', { exact: true }).fill('仅界面测试，不创建账号')
      await dialog.getByLabel('初始密码', { exact: true }).fill('SyntheticOnly123!')
      await withinViewport(dialog.getByRole('button', { name: '创建账号', exact: true }), 'account bottom action', width < 768 ? 44 : 0)
      assert.ok(await dialog.getByRole('button', { name: '创建账号', exact: true }).isEnabled())
      await noOverflow(page, 'account form dialog'); await screenshot(page, `${width}-11-account-dialog`)
      if (width < 768) {
        await page.setViewportSize({ width, height: 420 })
        await withinViewport(dialog.getByRole('button', { name: '创建账号', exact: true }), 'short viewport account action', 44)
        await noOverflow(page, 'short viewport account form')
        await screenshot(page, `${width}-12-short-viewport-dialog`)
        await page.setViewportSize({ width, height: 844 })
      }
      await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
      assert.ok(await create.evaluate(e => e === document.activeElement), 'dialog returns focus to opener')
      await create.click(); await dialog.getByRole('button', { name: '关闭账号窗口', exact: true }).click(); await dialog.waitFor({ state: 'hidden' })
    })
  }
} finally {
  await browser.close()
  await writeFile(path.join(artifacts, process.env.MOBILE_SCENARIOS ? 'results-subset.json' : 'results.json'), JSON.stringify({ url: baseURL, browser: 'local installed Edge, headless Playwright', syntheticAPI: true, businessWritesAllowed: false, widths, results }, null, 2))
  const raceResults = results.filter(result => /^\d+-async-/.test(result.name))
  if (raceResults.length) await writeFile(path.join(artifacts, 'race-results.json'), JSON.stringify({ url: baseURL, syntheticAPI: true, businessWritesAllowed: false,
    note: 'New async overlay race scenarios. Focus retests overlap the original 32 scenarios and are not additional unique coverage.',
    results: raceResults, focusRetests: results.filter(result => /^\d+-(navigation-dashboard|files-import-dialog)$/.test(result.name)),
  }, null, 2))
}
const failed = results.filter(result => !result.passed)
console.log(`${results.length - failed.length}/${results.length} responsive scenarios passed; screenshots contain synthetic data only: ${artifacts}`)
if (failed.length) process.exitCode = 1
