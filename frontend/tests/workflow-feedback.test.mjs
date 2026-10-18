import test from 'node:test'
import assert from 'node:assert/strict'
import { computed, ref, h, nextTick } from 'vue'
import { useReviewDrafts } from '../src/review-drafts.js'
import { compileComponent, renderer, descendants, textOf } from './component-test-utils.mjs'

const RefreshStatus = (await compileComponent('RefreshStatus')).default
const historyModule = await compileComponent('ReviewHistory')
const warningsModule = await compileComponent('ImportWarnings', [
  ["import Pagination from './Pagination.vue'", `import { h as testH } from 'vue'; const Pagination = { props:['page','total'], emits:['change'], render() { return testH('button', {onClick:()=>this.$emit('change',this.page+1)},'下一页警告') } }`],
])
function mount(component, props) {
  const root = { children:[] }, app = renderer.createApp({ render:()=>h(component,props) })
  app.mount(root); return { root, unmount:()=>app.unmount() }
}

test('unsubmitted comments are independent by account, record and revision, and only cleared explicitly', () => {
  const account = ref('a'), record = ref('ticket-a'), revision = ref('v1')
  const store = useReviewDrafts(computed(()=>`${account.value}:${record.value}:${revision.value}`))
  store.comment.value = '只填写审核意见，正文未改'
  revision.value = 'v2'; assert.equal(store.comment.value,'')
  store.comment.value = '第二版意见'
  revision.value = 'v1'; assert.equal(store.comment.value,'只填写审核意见，正文未改')
  record.value = 'ticket-b'; assert.equal(store.comment.value,'')
  record.value = 'ticket-a'; account.value='b'; assert.equal(store.comment.value,'')
  account.value='a'; assert.equal(store.comment.value,'只填写审核意见，正文未改')
  store.clear(); assert.equal(store.comment.value,'')
  revision.value='v2'; assert.equal(store.comment.value,'第二版意见')
  store.reset(); assert.equal(store.comment.value,'')
})

test('refresh failure states the stale-data risk, last successful time and an enabled retry action', async () => {
  let retries = 0
  const view = mount(RefreshStatus,{ error:'连接失败',lastSuccess:'2026-10-18T03:00:00Z',onRetry:()=>retries++ })
  try {
    assert.match(textOf(view.root),/更新失败.*连接失败.*可能已过期/)
    assert.match(textOf(view.root),/最后成功更新/)
    assert.equal(descendants(view.root).find(node=>node.type==='div').props.role,'alert')
    descendants(view.root).find(node=>node.type==='button').props.onClick()
    assert.equal(retries,1)
  } finally { view.unmount() }
})

test('review history identifies actor and exact revision and opens that revision', () => {
  const opened = [], view = mount(historyModule.default,{ reviews:[{ id:'review',action:'approve',actor_name:'审核员甲',actor_username:'reviewer-a',revision_id:'v2',revision_no:2,reason:'核对原文通过',created_at:'2026-10-18' }],onOpenRevision:id=>opened.push(id) })
  try {
    assert.match(textOf(view.root),/审核员甲（reviewer-a）/)
    assert.match(textOf(view.root),/版本 2/)
    assert.match(textOf(view.root),/核对原文通过/)
    descendants(view.root).find(node=>node.type==='button').props.onClick()
    assert.deepEqual(opened,['v2'])
  } finally { view.unmount() }
})

test('all import warnings are reachable in pages of ten and locate emits the original source index', async () => {
  const warnings = Array.from({length:13},(_,i)=>({index:i*2,message:`解析警告${i+1}`,source_line_start:i*4+1,source_line_end:i*4+3}))
  const located = [], view = mount(warningsModule.default,{ warnings,onLocate:warning=>located.push(warning) })
  try {
    assert.match(textOf(view.root),/发现 13 项解析警告/)
    assert.equal(descendants(view.root).filter(node=>node.type==='li').length,10)
    descendants(view.root).find(node=>node.type==='button' && textOf(node)==='下一页警告').props.onClick()
    await nextTick()
    assert.equal(descendants(view.root).filter(node=>node.type==='li').length,3)
    assert.match(textOf(view.root),/解析警告13/)
    const buttons = descendants(view.root).filter(node=>node.type==='button' && textOf(node)==='定位原文')
    buttons[2].props.onClick(); assert.deepEqual(located,[warnings[12]])
    assert.match(textOf(view.root),/原文第 49–51 行/)
  } finally { view.unmount() }
})
