import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import { compileComponent } from './component-test-utils.mjs'
const RefreshStatus = (await compileComponent('RefreshStatus')).default

// Render the actual component with an in-memory API; no live messages are changed.
const { descriptor } = parse(await readFile(new URL('../src/components/FileProcessing.vue', import.meta.url), 'utf8'))
const compiled = compileScript(descriptor, { id: 'file-processing-test', inlineTemplate: true }).content
  .replace("import { api } from '../api'", 'let apiHandler, scheduledRefresh; export function setApiHandler(handler) { apiHandler = handler }; export function firePoll() { return scheduledRefresh?.() }; function scheduleRefresh(callback) { scheduledRefresh=callback; return 0 }; const api = (...args) => apiHandler(...args)')
  .replace('setTimeout(() => loadLatest(true), 8000)', 'scheduleRefresh(() => loadLatest(true))')
  .replace("import ExtractionOptions from './ExtractionOptions.vue'", 'const ExtractionOptions = { render() { return null } }')
  .replace("import Pagination from './Pagination.vue'", 'const Pagination = { render() { return null } }')
  .replace("import RefreshStatus from './RefreshStatus.vue'", 'let RefreshStatus; export function setRefreshStatus(component) { RefreshStatus = component }')
  .replace("import '../file-processing.css'", '')
const compiledURL = new URL(`.file-processing-${process.pid}.mjs`, import.meta.url)
let Component, setApiHandler, firePoll
try {
  await writeFile(compiledURL, compiled)
  const module = await import(compiledURL.href)
  Component = module.default; setApiHandler = module.setApiHandler; firePoll=module.firePoll; module.setRefreshStatus(RefreshStatus)
} finally { await unlink(compiledURL).catch(() => {}) }

const renderer = createRenderer({
  createElement: type => ({ type, children: [], props: {}, text: '' }),
  createText: text => ({ type: '#text', text }),
  createComment: text => ({ type: '#comment', text }),
  insert(node, parent, anchor = null) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    node.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index >= 0) parent.children.splice(index, 0, node)
    else parent.children.push(node)
  },
  remove(node) { node.parent?.children.splice(node.parent.children.indexOf(node), 1) },
  setText(node, text) { node.text = text },
  setElementText(node, text) { node.text = text; node.children = [] },
  patchProp(node, key, previous, next) { node.props[key] = next },
  parentNode: node => node.parent,
  nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
})
function textOf(node) { return node.type === '#comment' ? '' : (node.text || '') + (node.children || []).map(textOf).join('') }
async function mount(counts, historical = 1, state = 'succeeded') {
  const latestJob = { id: 'job-a', batch_id: 'file-a', state, checkpoint: { needs_review_messages: historical, messages_done:5, messages_total:20 } }
  setApiHandler(async path => path.startsWith('/jobs?') ? { items: [latestJob] } : { items: [], page: 1, total: 0 })
  const props = reactive({ batch: { id: 'file-a', confirmed_at: '2026-10-16', message_counts: counts }, latestJob })
  const root = { type: 'root', children: [] }
  const app = renderer.createApp({ render: () => h(Component, props) })
  app.mount(root)
  await nextTick(); await nextTick()
  return { props, root, unmount: () => app.unmount() }
}

test('resolved messages clear a historical task warning and newly flagged messages update immediately', async () => {
  const view = await mount({ needs_review: 1, pending: 6 })
  try {
    assert.match(textOf(view.root), /当前还有 1 条消息需要人工归属/)
    view.props.batch = { ...view.props.batch, message_counts: { needs_review: 0, pending: 5 } }
    await nextTick()
    assert.doesNotMatch(textOf(view.root), /条消息需要人工归属|任务结束时还有/)
    assert.match(textOf(view.root), /当前没有需要人工归属的消息/)
    assert.equal(view.props.latestJob.checkpoint.needs_review_messages, 1)
    view.props.batch.message_counts.needs_review = 2
    await nextTick()
    assert.match(textOf(view.root), /当前还有 2 条消息需要人工归属/)
    assert.doesNotMatch(textOf(view.root), /当前没有需要人工归属的消息/)
  } finally { view.unmount() }
})

test('current review messages are shown even when the task ended with none', async () => {
  const view = await mount({ needs_review: 3, pending: 3 }, 0)
  try { assert.match(textOf(view.root), /当前还有 3 条消息需要人工归属/) }
  finally { view.unmount() }
})

test('missing current counts and deleted files do not claim that review is complete', async () => {
  const view = await mount({ pending: 0 })
  try {
    assert.doesNotMatch(textOf(view.root), /条消息需要人工归属|当前没有需要人工归属/)
    view.props.batch.message_counts.needs_review = 1
    view.props.batch.is_deleted = true
    await nextTick()
    assert.doesNotMatch(textOf(view.root), /条消息需要人工归属|当前没有需要人工归属/)
  } finally { view.unmount() }
})

test('an initial file progress read failure provides retry and recovers when the server responds', async () => {
  const view = await mount({ needs_review:0 })
  try {
    assert.match(textOf(view.root), /最后成功更新/)
    setApiHandler(async () => { throw new Error('服务器暂时不可用') })
    const findRetry = node => [node, ...(node.children || []).flatMap(findRetry)]
    // Replacing latestJob causes the same refresh path as returning to a file.
    view.props.batch = { ...view.props.batch, id:'file-b' }
    await nextTick(); await nextTick()
    assert.match(textOf(view.root), /更新失败.*服务器暂时不可用/)
    assert.match(textOf(view.root), /尚未成功获取最新进度/)
    const retry = findRetry(view.root).find(node => node.type === 'button' && textOf(node).includes('重试更新'))
    assert.ok(retry)
    setApiHandler(async path => path.startsWith('/jobs?') ? { items:[{ id:'job-b', batch_id:'file-b', state:'succeeded', checkpoint:{} }] } : { items:[], total:0, page:1 })
    await retry.props.onClick(); await nextTick(); await nextTick()
    assert.doesNotMatch(textOf(view.root), /更新失败|服务器暂时不可用/)
    assert.match(textOf(view.root), /最后成功更新/)
  } finally { view.unmount() }
})

test('background progress polling keeps its last success time and cached progress on failure', async () => {
  const view = await mount({ needs_review:0 },0,'running')
  const nodes = node => [node,...(node.children || []).flatMap(nodes)]
  try {
    const timeBefore=nodes(view.root).find(node=>node.type==='small'&&textOf(node).startsWith('最后成功更新')).text
    setApiHandler(async()=>{throw new Error('网络暂时断开')})
    await firePoll();await nextTick()
    assert.match(textOf(view.root),/更新失败.*网络暂时断开/)
    assert.match(textOf(view.root),/5 \/ 20/)
    assert.doesNotMatch(textOf(view.root),/进度会自动更新/)
    assert.equal(nodes(view.root).find(node=>node.type==='small'&&textOf(node).startsWith('最后成功更新')).text,timeBefore)
    setApiHandler(async path=>path.startsWith('/jobs?')?{items:[{...view.props.latestJob,state:'succeeded'}]}:{items:[],total:0,page:1})
    // Records read is independent of the progress retry in this test.
    await firePoll();await nextTick()
    assert.doesNotMatch(textOf(view.root),/更新失败.*网络暂时断开/)
  } finally {view.unmount()}
})
