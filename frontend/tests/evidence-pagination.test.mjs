import test from 'node:test'
import assert from 'node:assert/strict'
import { h, nextTick, reactive } from 'vue'
import { compileComponent, renderer, descendants, textOf } from './component-test-utils.mjs'

globalThis.document = {addEventListener(){},removeEventListener(){},activeElement:null}
globalThis.window = {getSelection:()=>null}
const Pagination = (await compileComponent('Pagination',[["import '../pagination-controls.css'",'']])).default
const module = await compileComponent('EvidencePicker',[
  ["import SearchSelect from './SearchSelect.vue'",'const SearchSelect = {render(){return null}}'],
  ["import Pagination from './Pagination.vue'",'let Pagination; export function setPagination(component) { Pagination=component }'],
  ["from '../editor-assist.js'","from '../src/editor-assist.js'"],
  ["import '../evidence-picker.css'",''],
])
module.setPagination(Pagination)
const flush = async()=>{await nextTick();await nextTick();await nextTick()}
function mount(count=25) {
  const messages=Array.from({length:count},(_,index)=>({id:`m${index+1}`,sender_name_raw:`成员${index+1}`,sent_at:'2026-10-18T09:00:00+08:00',source_filename:'测试聊天.txt',raw_text:`第 ${index+1} 条聊天原文${index%10===1?' 专属业务':''}`}))
  if(messages[20])messages[20].raw_text='前缀🙂定位目标后缀'
  const props=reactive({messages,fields:[{value:'problem',label:'问题描述'}],fieldKey:'problem',busy:false,focusRequest:null})
  const events=[],root={children:[]},app=renderer.createApp({render:()=>h(module.default,{...props,onAdd:value=>events.push(value)})})
  app.mount(root)
  return {root,props,events,unmount:()=>app.unmount()}
}
const messagesOf=view=>descendants(view.root).filter(node=>node.type==='article'&&node.props.class?.includes('evidence-picker__message'))
const originals=view=>descendants(view.root).filter(node=>node.type==='pre')
const button=(view,label)=>descendants(view.root).find(node=>node.type==='button'&&textOf(node)===label)
const list=view=>descendants(view.root).find(node=>node.props?.['aria-label']==='聊天原文列表')
async function click(view,label) {const target=button(view,label);assert.ok(target,`${label} exists`);target.props.onClick();await flush()}

test('source pagination is above the list, renders ten records per page and resets only the source scroll',async()=>{
  const view=mount()
  try {
    const nodes=descendants(view.root),pager=nodes.find(node=>node.props?.['aria-label']==='来源聊天分页')
    assert.ok(nodes.indexOf(pager)<nodes.indexOf(list(view)))
    assert.match(textOf(pager),/共 25 条 · 每页 10 条/)
    assert.equal(messagesOf(view).length,10);assert.equal(originals(view)[0].props['data-evidence-raw'],'m1')
    list(view).scrollTop=350;await click(view,'下一页')
    assert.equal(messagesOf(view).length,10);assert.equal(originals(view)[0].props['data-evidence-raw'],'m11')
    assert.equal(list(view).scrollTop,0)
    await click(view,'下一页');assert.equal(messagesOf(view).length,5)
    assert.match(textOf(pager),/第 3 \/ 3 页/);assert.equal(button(view,'下一页').props.disabled,true)
    assert.equal(view.props.messages.length,25)
  } finally {view.unmount()}
})

test('search from a later page starts at the first result page and clearing restores the full list',async()=>{
  const view=mount()
  try {
    await click(view,'下一页');await click(view,'下一页')
    const search=descendants(view.root).find(node=>node.props?.['aria-label']==='搜索来源聊天')
    search.props['onUpdate:modelValue']('专属业务');await flush()
    assert.equal(messagesOf(view).length,3);assert.equal(originals(view)[0].props['data-evidence-raw'],'m2')
    assert.match(textOf(view.root),/共 3 条 · 每页 10 条/)
    assert.equal(button(view,'下一页'),undefined)
    search.props['onUpdate:modelValue']('');await flush()
    assert.equal(messagesOf(view).length,10);assert.equal(originals(view)[0].props['data-evidence-raw'],'m1')
  } finally {view.unmount()}
})

test('evidence location clears search, opens the target page and highlights the exact Unicode excerpt',async()=>{
  const view=mount()
  try {
    const search=descendants(view.root).find(node=>node.props?.['aria-label']==='搜索来源聊天')
    search.props['onUpdate:modelValue']('专属业务');await flush()
    view.props.focusRequest={message_id:'m21',start_cp:3,end_cp:7,nonce:1};await flush()
    assert.equal(originals(view)[0].props['data-evidence-raw'],'m21')
    assert.equal(messagesOf(view).length,5)
    const mark=descendants(view.root).find(node=>node.type==='mark')
    assert.equal(textOf(mark),'定位目标');assert.equal(mark.scrolledIntoView,true)
    assert.equal(originals(view)[0].focused,true)
    assert.match(textOf(view.root),/第 3 \/ 3 页/)
    assert.match(textOf(view.root),/已定位来源聊天，第 3 页/)
    search.props['onUpdate:modelValue']('专属业务');await flush()
    assert.doesNotMatch(textOf(view.root),/已定位来源聊天，第 3 页/)
  } finally {view.unmount()}
})

test('quoting a message on another page uses its original ID and exact content; busy blocks paging',async()=>{
  const view=mount()
  try {
    await click(view,'下一页')
    const quote=descendants(messagesOf(view)[0]).find(node=>node.type==='button')
    quote.props.onClick();await flush()
    assert.deepEqual(view.events,[{message_id:'m11',exact_excerpt:view.props.messages[10].raw_text,occurrence:1,field_key:'problem'}])
    view.props.busy=true;await flush();assert.equal(button(view,'下一页').props.disabled,true)
    await click(view,'下一页');assert.equal(originals(view)[0].props['data-evidence-raw'],'m11')
  } finally {view.unmount()}
})

test('a shrinking source list clamps the page and an empty list remains readable',async()=>{
  const view=mount()
  try {
    await click(view,'下一页');await click(view,'下一页')
    view.props.messages=view.props.messages.slice(0,5);await flush()
    assert.equal(messagesOf(view).length,5);assert.equal(originals(view)[0].props['data-evidence-raw'],'m1')
    view.props.messages=[];await flush()
    assert.equal(messagesOf(view).length,0);assert.match(textOf(view.root),/共 0 条 · 每页 10 条/)
    assert.match(textOf(view.root),/暂无来源聊天/)
  } finally {view.unmount()}
})
