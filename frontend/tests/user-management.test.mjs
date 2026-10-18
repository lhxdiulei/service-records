import test from 'node:test'
import assert from 'node:assert/strict'
import { h, nextTick } from 'vue'
import { compileComponent, renderer, descendants, textOf } from './component-test-utils.mjs'
globalThis.document ??= { activeElement: null }
const module = await compileComponent('UserManagement', [
  ["import { api } from '../api'", 'let handler; export function setApi(next) { handler = next }; const api = (...args) => handler(...args)'],
  ["import Pagination from './Pagination.vue'", `import { h as testH } from 'vue'; const Pagination = { props:['page','total','disabled'], emits:['change'], render() { return testH('button', { disabled:this.disabled || this.page*10>=this.total, onClick:()=>this.$emit('change',this.page+1) }, '测试下一页') } }`],
  ["import '../user-management.css'", ''],
])
const Component = module.default
const flush = async () => { await new Promise(setImmediate); await nextTick() }
function button(view, label) {
  const item = descendants(view.root).find(node => node.type === 'button' && (node.props['aria-label'] === label || textOf(node) === label))
  assert.ok(item, `button ${label} exists`); return item
}
async function click(view, label) {
  const target = button(view, label)
  assert.ok(!target.props.disabled, `${label} enabled`)
  await target.props.onClick({ currentTarget: { focus() {} } }); await flush()
}
async function fill(view, label, value) {
  const targetLabel = descendants(view.root).find(node => node.type === 'label' && textOf(node) === label)
  assert.ok(targetLabel, `label ${label} exists`)
  const input = descendants(targetLabel).find(node => node.type === 'input')
  input.props['onUpdate:modelValue'](value); await nextTick()
}
async function mount() {
  const accounts = Array.from({ length:12 }, (_,index) => ({ id:`user-${index}`, username:`user${String(index).padStart(2,'0')}`, display_name:`姓名${index}`, role:index===0?'admin':'agent', version:1, disabled_at:null, created_at:'2026-10-18', last_login_at:null }))
  const calls = [], events = [], state = { accounts, failUpdate:false }
  module.setApi(async (path, options = {}) => {
    calls.push({ path, ...structuredClone(options) })
    const url = new URL(path, 'http://fixture'), method = options.method || 'GET'
    if (url.pathname === '/users' && method === 'GET') {
      const page = Number(url.searchParams.get('page')), status = url.searchParams.get('status'), query = (url.searchParams.get('q') || '').toLowerCase(), role = url.searchParams.get('role')
      const items = accounts.filter(a => (status==='all' || (status==='deleted')===!!a.disabled_at) && (!role || a.role===role) && (a.username+' '+a.display_name).toLowerCase().includes(query))
      return { items:structuredClone(items.slice((page-1)*10,page*10)), page, total:items.length }
    }
    if (url.pathname === '/users' && method === 'POST') {
      const item = { id:`user-${accounts.length}`, username:options.body.username, display_name:options.body.display_name, role:options.body.role, version:1, disabled_at:null }
      accounts.push(item); return structuredClone(item)
    }
    const id = url.pathname.split('/')[2], item = accounts.find(a => a.id === id)
    assert.ok(item, `fixture account ${id} exists`)
    if (method === 'GET') return structuredClone(item)
    assert.equal(options.version,item.version)
    if (method === 'PATCH') {
      if (state.failUpdate) throw Object.assign(new Error('数据已变化，请刷新后重试'),{ status:412 })
      Object.assign(item,{ username:options.body.username, display_name:options.body.display_name, role:options.body.role, version:item.version+1 })
    } else { item.disabled_at = method === 'DELETE' ? '2026-10-18' : null; item.version++ }
    return structuredClone(item)
  })
  const root = { children:[] }, app = renderer.createApp({ render:()=>h(Component,{ currentUser:accounts[0], onSelfUpdated:value=>events.push(value) }) })
  app.mount(root); await flush()
  return { root, calls, state, events, unmount:()=>app.unmount() }
}

test('users render ten per page without nickname controls and request the next page from the server', async () => {
  const view = await mount()
  try {
    assert.equal(descendants(view.root).filter(node=>node.type==='tr').length,11)
    assert.doesNotMatch(textOf(view.root),/微信昵称/)
    assert.equal(button(view,'删除账号 user00').props.disabled,true)
    await click(view,'测试下一页')
    assert.match(view.calls.at(-1).path,/page=2&page_size=10/)
    assert.match(textOf(view.root),/user10/)
    assert.doesNotMatch(textOf(view.root),/user01/)
  } finally { view.unmount() }
})

test('create and edit use a dialog and omit an unchanged password and all nickname fields', async () => {
  const view = await mount()
  try {
    await click(view,'新增账号')
    await fill(view,'用户名','newagent'); await fill(view,'显示姓名','新客服'); await fill(view,'初始密码','fixture-password-2026')
    const form = descendants(view.root).find(node=>node.type==='form')
    await form.props.onSubmit({ preventDefault() {} }); await flush()
    const create = view.calls.find(call=>call.method==='POST')
    assert.deepEqual(create.body,{ username:'newagent', display_name:'新客服', role:'agent', password:'fixture-password-2026' })
    await click(view,'编辑账号 user01'); await fill(view,'显示姓名','已修改姓名')
    const edit = descendants(view.root).find(node=>node.type==='form')
    await edit.props.onSubmit({ preventDefault() {} }); await flush()
    const update = view.calls.find(call=>call.method==='PATCH')
    assert.equal(update.version,1); assert.equal(update.body.display_name,'已修改姓名')
    assert.ok(!('password' in update.body)); assert.ok(!('wechat_nicknames' in update.body))
    assert.match(textOf(view.root),/账号已更新/)
  } finally { view.unmount() }
})

test('delete requires confirmation and removes the row while preserving an erroring edit for correction', async () => {
  const view = await mount()
  try {
    await click(view,'删除账号 user01')
    assert.equal(view.calls.filter(call=>call.method==='DELETE').length,0)
    assert.match(textOf(view.root),/历史工单、QA 和审核记录会保留/)
    await click(view,'确认删除账号')
    assert.equal(view.calls.filter(call=>call.method==='DELETE').length,1)
    assert.doesNotMatch(textOf(view.root),/姓名1编辑/)
    assert.ok(view.state.accounts[1].disabled_at)
    await click(view,'编辑账号 user02'); await fill(view,'显示姓名','冲突时保留的修改')
    view.state.failUpdate = true
    await descendants(view.root).find(node=>node.type==='form').props.onSubmit({ preventDefault() {} }); await flush()
    assert.match(textOf(view.root),/数据已变化/)
    assert.equal(descendants(view.root).find(node=>node.type==='input' && node.value==='冲突时保留的修改')?.value,'冲突时保留的修改')
  } finally { view.unmount() }
})

test('search resets pagination and deleted accounts can be found and restored with their current version', async () => {
  const view = await mount()
  try {
    await click(view,'测试下一页')
    const search = descendants(view.root).find(node=>node.type==='input' && node.props['aria-label']==='搜索账号')
    search.props['onUpdate:modelValue']('姓名11')
    await nextTick(); await new Promise(resolve=>setTimeout(resolve,280)); await flush()
    assert.match(view.calls.at(-1).path,/page=1&page_size=10/)
    assert.equal(new URL(view.calls.at(-1).path,'http://fixture').searchParams.get('q'),'姓名11')
    assert.match(textOf(view.root),/user11/); assert.doesNotMatch(textOf(view.root),/user10/)
    await click(view,'删除账号 user11'); await click(view,'确认删除账号')
    assert.match(textOf(view.root),/没有符合条件的账号/)
    const filter = descendants(view.root).find(node=>node.type==='select' && node.props['aria-label']==='账号状态筛选')
    filter.props['onUpdate:modelValue']('deleted')
    await nextTick(); await new Promise(resolve=>setTimeout(resolve,280)); await flush()
    await click(view,'恢复账号 user11'); await click(view,'确认恢复账号')
    const restore = view.calls.find(call=>call.path.endsWith('/restore'))
    assert.equal(restore.method,'POST'); assert.equal(restore.version,2)
    assert.equal(view.state.accounts[11].disabled_at,null)
  } finally { view.unmount() }
})
