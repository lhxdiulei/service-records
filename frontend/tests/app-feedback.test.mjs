import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { nextTick } from 'vue'
import { renderer } from './component-test-utils.mjs'

const raw = await readFile(new URL('../src/App.vue',import.meta.url),'utf8')
const exposed = 'defineExpose({ user, ready, detail, kind, revisionId, editing, comment, page, jobs, jobRefresh, selected, assignTitle, messageAssignIssue, preview, previewFocusIndex, previewScreening, error, setRevision, selectRevision, allowDiscardEdits, protectUnsaved, closeDetail, refreshJobs, fetchPage, locatePreviewWarning, assign, openAssignedIssue, addNote, review })'
const { descriptor } = parse(raw.replace('</script>', `\n${exposed}\n</script>`))
let compiled = compileScript(descriptor,{id:'app-feedback-test',inlineTemplate:true}).content
  .replace("import { api, loadCsrf, resetCsrf } from './api'", 'let handler; export function setApi(next) { handler=next }; const api=(...args)=>handler(...args); const loadCsrf=async()=>{}; const resetCsrf=()=>{}')
  .replace(/^import (\w+) from '\.\/components\/[^']+'$/gm, 'const $1 = { render() { return null } }')
  .replace(/^import '\.\/[^']+\.css'$/gm,'')
  .replaceAll("from './", "from '../src/")
const compiledURL = new URL(`.app-feedback-${process.pid}.mjs`,import.meta.url)
let module
try { await writeFile(compiledURL,compiled); module=await import(compiledURL.href) }
finally { await unlink(compiledURL).catch(()=>{}) }

const flush = async()=>{ await new Promise(setImmediate); await nextTick() }
function revision(id='v1',no=1) { return { id,revision_no:no,state:'draft',state_version:1,title:'字段咨询',problem_text:'问题',impact_text:'',handling_summary:'',current_conclusion:'',status:'open',claims:[],next_actions:[],evidence:[],date_basis:'first_question' } }
function record(id='ticket-a') { return { object:{id,ticket_no:'TK-A',version:1,current_revision_id:null,issue_id:'issue-a'},revisions:[revision(),revision('v2',2)],source_messages:[],reviews:[],notes:[],participants:[] } }
async function mount() {
  const calls=[], state={ handler:null, confirmations:0, allowLeave:false, focuses:[], scrolls:[] }
  globalThis.window = {matchMedia(){return {matches:false,addEventListener(){},removeEventListener(){}}},scrollY:0,scrollTo(){},addEventListener(){},removeEventListener(){},confirm(){state.confirmations++;return state.allowLeave}}
  globalThis.document = {body:{style:{overflow:""}},querySelector(){return null},activeElement:null,getElementById(id){return {focus(){state.focuses.push(id)},scrollIntoView(){state.scrolls.push(id)}}}}
  module.setApi(async(path,options={})=>{
    calls.push({path,...structuredClone(options)})
    if (state.handler) { const value=await state.handler(path,options); if (value!==undefined) return value }
    if(path==='/auth/me') return {id:'admin-a',username:'admin',display_name:'管理员',role:'admin'}
    if(path==='/issues'||path==='/integrations/dify')return []
    if(path==='/overview')return {tickets:0,qa:0,reviews:0,unassigned_messages:0}
    return {items:[],total:0,page:1,page_size:10}
  })
  const root={children:[]},app=renderer.createApp(module.default),vm=app.mount(root)
  await flush(); await flush()
  return {vm,calls,state,unmount:()=>app.unmount()}
}

test('opinion-only input survives version switches, blocks leaving and activates the unload warning',async()=>{
  const view=await mount(),{vm,state}=view
  try {
    vm.detail=record();vm.revisionId='v1';vm.setRevision();await nextTick()
    vm.comment='只写意见，不改正文';assert.equal(vm.editing,false)
    assert.equal(vm.allowDiscardEdits(),false)
    let prevented=false;const event={preventDefault(){prevented=true}}
    vm.protectUnsaved(event);assert.equal(prevented,true);assert.equal(event.returnValue,'')
    const confirmations=state.confirmations
    assert.equal(vm.selectRevision('v2'),true);assert.equal(vm.comment,'')
    vm.comment='第二版内部备注';vm.selectRevision('v1')
    assert.equal(vm.comment,'只写意见，不改正文');assert.equal(state.confirmations,confirmations)
    await vm.closeDetail();assert.equal(vm.detail.object.id,'ticket-a')
    vm.editing=true;assert.equal(vm.selectRevision('v2'),false);assert.equal(vm.comment,'只写意见，不改正文')
    vm.editing=false;state.allowLeave=true;await vm.closeDetail();assert.equal(vm.detail,null)
    vm.detail=record();vm.revisionId='v1';vm.setRevision();assert.equal(vm.comment,'只写意见，不改正文')
  } finally {view.unmount()}
})

test('failed note/review requests retain opinions; successful note saves clear only that revision',async()=>{
  const view=await mount(),{vm,state}=view
  try {
    vm.detail=record();vm.revisionId='v2';vm.setRevision();vm.comment='另一版意见'
    vm.selectRevision('v1');vm.comment='请补充字段说明'
    state.handler=async(path)=>{if(path.includes('/notes')||path.endsWith('/reject'))throw new Error('连接断开')}
    await vm.addNote();assert.equal(vm.comment,'请补充字段说明')
    await vm.review('reject');assert.equal(vm.comment,'请补充字段说明')
    state.handler=async(path)=>path.endsWith('/notes')?{id:'note-a',body:'请补充字段说明'}:undefined
    await vm.addNote();assert.equal(vm.comment,'');assert.equal(vm.detail.notes.length,1)
    vm.selectRevision('v2');assert.equal(vm.comment,'另一版意见')
  } finally {view.unmount()}
})

test('AI task refresh failure preserves previous progress and time, with recovery on retry',async()=>{
  const view=await mount(),{vm,state}=view
  try {
    const job={id:'job-a',state:'running',checkpoint:{messages_done:5,messages_total:20}}
    state.handler=async(path)=>path.startsWith('/jobs?')?{items:[job],total:1,page:1}:undefined
    await vm.refreshJobs();const previousTime=vm.jobRefresh.lastSuccess
    state.handler=async(path)=>{if(path.startsWith('/jobs?'))throw new Error('任务服务不可用')}
    await vm.refreshJobs();assert.equal(vm.jobRefresh.error,'任务服务不可用')
    assert.equal(vm.jobRefresh.lastSuccess,previousTime);assert.equal(vm.jobs[0].checkpoint.messages_done,5)
    state.handler=async(path)=>path.startsWith('/jobs?')?{items:[{...job,state:'succeeded'}],total:1,page:1}:undefined
    await vm.refreshJobs();assert.equal(vm.jobRefresh.error,'');assert.equal(vm.jobs[0].state,'succeeded')
  } finally {view.unmount()}
})

test('locating a warning switches to all records and the source page, then focuses its exact original',async()=>{
  const view=await mount(),{vm,state,calls}=view
  try {
    vm.preview={batch:{id:'file-a'},page:1,records:[],warnings:[]};vm.previewScreening='filtered'
    state.handler=async(path)=>path.startsWith('/imports/file-a/preview?')?{batch:{id:'file-a'},total:24,page:3,records:[{source_index:23}],warnings:[]}:undefined
    await vm.locatePreviewWarning({index:23,message:'时间格式无效'})
    assert.match(calls.at(-1).path,/page=3&page_size=10&screening=all/)
    assert.equal(vm.previewScreening,'all');assert.equal(vm.previewFocusIndex,23)
    assert.deepEqual(state.focuses,['preview-source-23']);assert.deepEqual(state.scrolls,['preview-source-23'])
  } finally {view.unmount()}
})

test('a superseded background refresh failure cannot replace a newer successful task status',async()=>{
  const view=await mount(),{vm,state}=view
  try {
    let rejectOld,calls=0
    state.handler=async(path)=>{
      if(!path.startsWith('/jobs?'))return
      if(++calls===1)return await new Promise((resolve,reject)=>{rejectOld=reject})
      return {items:[{id:'new-job',state:'succeeded'}],total:1,page:1}
    }
    const old=vm.refreshJobs()
    await vm.fetchPage('jobs');const time=vm.jobRefresh.lastSuccess
    rejectOld(new Error('旧请求超时'));await old
    assert.equal(vm.jobRefresh.error,'');assert.equal(vm.jobRefresh.lastSuccess,time)
    assert.equal(vm.jobs[0].id,'new-job')
  } finally {view.unmount()}
})

test('new and existing assignments open their corresponding ticket without creating duplicate issues',async()=>{
  for (const existing of [false,true]) {
    const view=await mount(),{vm,state,calls}=view
    try {
      vm.page='messages';vm.selected=['message-a'];vm.assignTitle='字段咨询';vm.messageAssignIssue=existing?'issue-a':'__new__'
      state.handler=async(path,options)=>{
        if(path==='/issues'&&options.method==='POST')return {issue:{id:'issue-a',label:'字段咨询'},ticket:{id:'ticket-a'}}
        if(path==='/issues/issue-a')return {issue:{id:'issue-a',label:'字段咨询',version:1},ticket_id:'ticket-a',messages:[{id:'old-message',relation:'question'}]}
        if(path==='/issues/issue-a/messages')return {id:'issue-a'}
        if(path==='/tickets/ticket-a')return record()
      }
      await vm.assign();assert.equal(vm.detail.object.id,'ticket-a');assert.equal(vm.page,'messages');assert.deepEqual([...vm.selected],[])
      assert.equal(calls.filter(c=>c.path==='/issues'&&c.method==='POST').length,existing?0:1)
      if(existing)assert.equal(calls.find(c=>c.path==='/issues/issue-a/messages').body.messages.length,2)
      await vm.assign();assert.equal(calls.filter(c=>c.path==='/issues'&&c.method==='POST').length,existing?0:1)
    } finally {view.unmount()}
  }
})
