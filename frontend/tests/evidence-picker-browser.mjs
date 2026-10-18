// Isolated browser regression for source selection; synthetic data, no API calls.
// Start Vite on 127.0.0.1:5173, then run this script with Node.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { loadChromium } from './browser-utils.mjs'
const chromium = await loadChromium()
const baseURL = process.env.EVIDENCE_PICKER_BROWSER_URL || 'http://127.0.0.1:5173'
const artifacts = fileURLToPath(new URL('../test-results/evidence-picker/', import.meta.url))
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
const context = await browser.newContext({ viewport: { width: 1200, height: 900 } })
const page = await context.newPage()
const failures = [], results = []
page.on('pageerror', error => failures.push(error.message))
const harness = `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><title>Evidence picker regression</title></head><body><div id="app" style="max-width:660px;margin:24px auto"></div><script type="module">
import { createApp, h, reactive } from '/node_modules/.vite/deps/vue.js'
import EvidencePicker from '/src/components/EvidencePicker.vue'
import '/src/style.css'
const messages = Array.from({length:12}, (_,i) => ({id:'m'+(i+1),sender_name_raw:'成员'+(i+1),raw_text:'原文'+(i+1),sent_at:'2026-10-16T09:00:00+08:00',source_filename:'合成聊天.txt',is_deleted:false}))
messages[0].raw_text='😀重复答案\\r\\n中间说明😀重复答案尾部'.replaceAll('\\\\r','\\r').replaceAll('\\\\n','\\n')
messages[1].raw_text='另一条原文'
messages[2].raw_text='删除记录只读';messages[2].is_deleted=true
messages[10].raw_text='前缀🙂定位目标后缀'
const state = reactive({messages,fields:[{value:'problem',label:'问题描述',description:'说明客户问题',preview:'客户遇到了什么问题？'},{value:'answer',label:'回答内容',preview:'建议操作步骤'}],fieldKey:'problem',busy:false,focusRequest:null,selectionRequest:null})
window.evidenceFixture={state,events:[]}
createApp({render:()=>h(EvidencePicker,{...state,'onUpdate:fieldKey':v=>state.fieldKey=v,onAdd:v=>window.evidenceFixture.events.push(v)})}).mount('#app')
</script></body></html>`
await page.route('**/evidence-picker-harness', route => route.fulfill({ status: 200, contentType: 'text/html', body: harness }))
await page.route('**/api/**', route => { failures.push('Unexpected API request'); return route.abort() })
async function reset() {
  await page.goto(`${baseURL}/evidence-picker-harness`)
  await page.locator('[data-evidence-raw="m1"]').waitFor()
}
async function select(messageId, start, end, endMessageId = messageId) {
  await page.evaluate(({ messageId, start, end, endMessageId }) => {
    function position(pre, offset) {
      const walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT)
      let node
      while ((node = walker.nextNode())) {
        if (offset <= node.textContent.length) return [node, offset]
        offset -= node.textContent.length
      }
      throw Error('Invalid fixture text offset')
    }
    const from = position(document.querySelector(`[data-evidence-raw="${messageId}"]`), start)
    const to = position(document.querySelector(`[data-evidence-raw="${endMessageId}"]`), end)
    const range = document.createRange(); range.setStart(...from); range.setEnd(...to)
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  }, { messageId, start, end, endMessageId })
}
const emitted = () => page.evaluate(() => window.evidenceFixture.events)
async function run(name, task) {
  await reset()
  await task()
  assert.deepEqual(failures, [], 'No browser exceptions or API calls')
  results.push({ name, passed: true })
  console.log(`PASS ${name}`)
}
try {
  await run('selected second identical Unicode excerpt preserves its actual occurrence', async () => {
    const offsets = await page.evaluate(() => { const raw=window.evidenceFixture.state.messages[0].raw_text,excerpt='😀重复答案';const start=raw.lastIndexOf(excerpt);return {start,end:start+excerpt.length} })
    await select('m1', offsets.start, offsets.end)
    await page.getByRole('button', { name: '引用选中文字', exact: true }).click()
    assert.deepEqual(await emitted(), [{ message_id: 'm1', exact_excerpt: '😀重复答案', occurrence: 2, field_key: 'problem' }])
  })
  await run('selection spanning two messages cannot be cited', async () => {
    await select('m1', 0, 4)
    assert.equal(await page.getByRole('button', { name: '引用选中文字', exact: true }).count(), 1)
    await select('m1', 0, 3, 'm2')
    assert.equal(await page.getByRole('button', { name: '引用选中文字', exact: true }).count(), 0)
    assert.deepEqual(await emitted(), [])
  })
  await run('whole-message fallback preserves raw whitespace and deleted sources remain read-only', async () => {
    const raw = await page.evaluate(() => window.evidenceFixture.state.messages[0].raw_text)
    assert.ok(raw.includes('\r\n'), 'Fixture covers literal CRLF')
    await page.locator('.evidence-picker__message').filter({ has: page.locator('[data-evidence-raw="m1"]') }).getByRole('button', { name: '引用整条消息' }).click()
    assert.deepEqual(await emitted(), [{ message_id: 'm1', exact_excerpt: raw, occurrence: 1, field_key: 'problem' }])
    await select('m3', 0, 4)
    assert.equal(await page.getByRole('button', { name: '引用选中文字', exact: true }).count(), 0)
    assert.equal(await page.locator('.evidence-picker__message').filter({ has: page.locator('[data-evidence-raw="m3"]') }).getByRole('button').count(), 0)
  })
  await run('focus clears search and reaches message 11 with correct codepoint highlight', async () => {
    await page.getByRole('searchbox', { name: '搜索来源聊天' }).fill('另一条原文')
    await page.evaluate(() => { window.evidenceFixture.state.focusRequest={message_id:'m11',start_cp:3,end_cp:7,nonce:1} })
    await page.locator('[data-evidence-raw="m11"] mark').waitFor()
    assert.equal(await page.getByRole('searchbox', { name: '搜索来源聊天' }).inputValue(), '')
    assert.equal(await page.locator('[data-evidence-raw="m11"] mark').textContent(), '定位目标')
    assert.match(await page.getByRole('navigation', { name: '来源聊天分页' }).textContent(), /第 2 \/ 2 页/)
    await page.screenshot({ path: `${artifacts}/located-source.png`, fullPage: true })
    await select('m11', 2, 6)
    await page.getByRole('button', { name: '引用选中文字', exact: true }).click()
    assert.deepEqual(await emitted(), [{ message_id: 'm11', exact_excerpt: '🙂定位', occurrence: 1, field_key: 'problem' }])
  })
  await run('manual repeated text requires explicit occurrence and exact raw match', async () => {
    await page.getByText('手动粘贴原文', { exact: true }).click()
    await page.getByRole('combobox', { name: '手动引用的来源聊天' }).fill('成员1')
    await page.getByRole('option').filter({ hasText: '😀重复答案' }).click()
    await page.getByRole('textbox', { name: '手动粘贴的原文' }).fill('😀重复答案')
    assert.equal(await page.getByRole('button', { name: '添加原文引用' }).isDisabled(), true)
    await page.getByRole('combobox', { name: '相同原文的位置' }).selectOption('2')
    await page.getByRole('button', { name: '添加原文引用' }).click()
    assert.deepEqual(await emitted(), [{ message_id: 'm1', exact_excerpt: '😀重复答案', occurrence: 2, field_key: 'problem' }])
    await page.getByRole('textbox', { name: '手动粘贴的原文' }).fill('不在原文里的改写')
    assert.equal(await page.getByRole('button', { name: '添加原文引用' }).isDisabled(), true)
    assert.match(await page.locator('.evidence-picker__validation').textContent(), /未找到完全一致/)
  })
  await run('field requests direct new citations and busy disables mutation controls', async () => {
    await page.evaluate(() => { window.evidenceFixture.state.selectionRequest={field_key:'answer',nonce:1} })
    await page.waitForFunction(() => window.evidenceFixture.state.fieldKey === 'answer')
    assert.match(await page.locator('.evidence-picker__target').textContent(), /回答内容/)
    await page.locator('.evidence-picker__message').filter({ has: page.locator('[data-evidence-raw="m2"]') }).getByRole('button').click()
    assert.equal((await emitted())[0].field_key, 'answer')
    await page.evaluate(() => { window.evidenceFixture.state.busy=true })
    assert.equal(await page.getByRole('searchbox', { name: '搜索来源聊天' }).isDisabled(), true)
    assert.ok((await page.locator('.evidence-picker button').evaluateAll(nodes=>nodes.every(node=>node.disabled))))
    await select('m1', 0, 4)
    assert.equal(await page.getByRole('button', { name: '引用选中文字', exact: true }).count(), 0)
    assert.equal((await emitted()).length, 1)
  })
  await run('keyboard selection is captured and changed DOM text is rejected', async () => {
    await page.evaluate(() => {
      const pre=document.querySelector('[data-evidence-raw="m2"]'),text=pre.firstChild,selection=window.getSelection()
      pre.focus();selection.removeAllRanges();const range=document.createRange();range.setStart(text,0);range.collapse(true);selection.addRange(range)
    })
    await page.keyboard.press('Shift+ArrowRight')
    await page.keyboard.press('Shift+ArrowRight')
    await page.getByRole('button', { name: '引用选中文字', exact: true }).click()
    assert.equal((await emitted())[0].exact_excerpt, '另一')
    await page.evaluate(() => { document.querySelector('[data-evidence-raw="m1"]').textContent='渲染已变更，不能匹配原文' })
    await select('m1', 0, 4)
    assert.equal(await page.getByRole('button', { name: '引用选中文字', exact: true }).count(), 0)
  })
  await writeFile(`${artifacts}/results.json`, JSON.stringify({ passed: results.length, results }, null, 2))
  console.log(`${results.length} evidence picker browser scenarios passed`)
} finally {
  await browser.close()
}
