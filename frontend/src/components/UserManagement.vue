<script setup>
import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import { Plus, Search, X, Users } from 'lucide-vue-next'
import { api } from '../api'
import Pagination from './Pagination.vue'
import '../user-management.css'

const props = defineProps({ currentUser: { type: Object, required: true }, reloadToken: { type: Number, default: 0 } })
const emit = defineEmits(['self-updated', 'reauthenticate'])
const users = ref([]), page = ref(1), total = ref(0), query = ref(''), role = ref(''), status = ref('active')
const listBusy = ref(false), busy = ref(false), reading = ref(false), loadError = ref(''), formError = ref(''), notice = ref('')
const editor = ref(null), dialogTitle = ref(null)
const form = reactive({ username: '', display_name: '', role: 'agent', password: '' })
const roleNames = { admin: '管理员', agent: '客服', reviewer: '审核员' }
const titles = { create: '新增账号', edit: '编辑账号', view: '账号详情', delete: '删除账号', restore: '恢复账号' }
const validForm = computed(() => form.username.trim().length >= 2 && !!form.display_name.trim() &&
  (editor.value?.mode === 'create' ? form.password.length >= 12 : !form.password || form.password.length >= 12))
let alive = true, request = 0, dialogRequest = 0, searchTimer, returnFocus
function date(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }

async function loadUsers(next = page.value) {
  if (!alive) return
  clearTimeout(searchTimer)
  const token = ++request
  listBusy.value = true; loadError.value = ''
  const params = new URLSearchParams({ page: String(next), page_size: '10', status: status.value })
  if (query.value.trim()) params.set('q', query.value.trim())
  if (role.value) params.set('role', role.value)
  try {
    const result = await api(`/users?${params}`)
    if (!alive || token !== request) return
    const last = Math.max(1, Math.ceil(result.total / 10))
    if (next > last) return await loadUsers(last)
    users.value = result.items; page.value = result.page; total.value = result.total
  } catch (error) { if (alive && token === request) loadError.value = error.message }
  finally { if (alive && token === request) listBusy.value = false }
}
function search() {
  clearTimeout(searchTimer); ++request
  page.value = 1; listBusy.value = true
  searchTimer = setTimeout(() => loadUsers(1), 250)
}
async function openDialog(mode, account = null, event = null) {
  if (busy.value || listBusy.value) return
  returnFocus = event?.currentTarget || returnFocus
  const token = ++dialogRequest
  formError.value = ''; notice.value = ''; editor.value = { mode, target: null }
  Object.assign(form, { username: '', display_name: '', role: 'agent', password: '' })
  await nextTick(); dialogTitle.value?.focus?.()
  if (!account) return
  reading.value = true
  try {
    const target = await api(`/users/${account.id}`)
    if (!alive || token !== dialogRequest) return
    editor.value.target = target
    Object.assign(form, { username: target.username, display_name: target.display_name, role: target.role })
  } catch (error) { if (alive && token === dialogRequest) formError.value = error.message }
  finally { if (alive && token === dialogRequest) reading.value = false }
}
function closeDialog(force = false) {
  if (busy.value && !force) return
  ++dialogRequest; editor.value = null; form.password = ''; reading.value = false; formError.value = ''
  nextTick(() => returnFocus?.focus?.())
}
async function submit() {
  if (busy.value || reading.value || !editor.value || !validForm.value) return
  const { mode, target } = editor.value
  if (!['create','edit'].includes(mode) || mode === 'edit' && !target) return
  busy.value = true; formError.value = ''; notice.value = ''
  const body = { username: form.username.trim(), display_name: form.display_name.trim(), role: form.role }
  if (mode === 'create' || form.password) body.password = form.password
  try {
    const result = await api(mode === 'create' ? '/users' : `/users/${target.id}`, { method: mode === 'create' ? 'POST' : 'PATCH', body, ...(target ? { version: target.version } : {}) })
    if (!alive) return
    closeDialog(true)
    if (result.id === props.currentUser.id) {
      if (result.reauthenticate_self) { emit('reauthenticate', '账号登录信息已更新，请重新登录'); return }
      emit('self-updated', result)
    }
    notice.value = mode === 'create' ? '账号已创建' : '账号已更新'
    await loadUsers(mode === 'create' ? 1 : page.value)
  } catch (error) { if (alive) formError.value = error.message }
  finally { if (alive) busy.value = false }
}
async function confirmAccountAction() {
  if (busy.value || reading.value || !editor.value?.target) return
  const { mode, target } = editor.value
  if (!['delete','restore'].includes(mode) || mode === 'delete' && target.id === props.currentUser.id) return
  busy.value = true; formError.value = ''; notice.value = ''
  try {
    await api(`/users/${target.id}${mode === 'restore' ? '/restore' : ''}`, { method: mode === 'restore' ? 'POST' : 'DELETE', version: target.version })
    if (!alive) return
    closeDialog(true); notice.value = mode === 'restore' ? '账号已恢复，可以重新登录' : '账号已删除，历史记录已保留'
    await loadUsers()
  } catch (error) { if (alive) formError.value = error.message }
  finally { if (alive) busy.value = false }
}
watch([query,role,status], search)
watch(() => props.reloadToken, () => loadUsers(), { immediate: true })
onUnmounted(() => { alive = false; ++request; ++dialogRequest; clearTimeout(searchTimer); form.password = '' })
</script>

<template>
  <section class="panel user-management" aria-label="用户管理">
    <div class="section-line"><div><h3><Users :size="18"/>用户列表</h3><p class="hint">管理员维护内部账号。聊天发送人可按账号用户名或显示姓名识别。</p></div><button type="button" class="primary" :disabled="busy || listBusy" @click="openDialog('create', null, $event)"><Plus :size="16"/>新增账号</button></div>
    <div class="user-list-toolbar">
      <label class="user-search"><Search :size="16"/><input v-model="query" type="search" maxlength="200" aria-label="搜索账号" placeholder="搜索用户名或显示姓名" :disabled="busy"/></label>
      <select v-model="role" aria-label="账号角色筛选" :disabled="busy"><option value="">全部角色</option><option v-for="(label,value) in roleNames" :key="value" :value="value">{{label}}</option></select>
      <select v-model="status" aria-label="账号状态筛选" :disabled="busy"><option value="active">正常账号</option><option value="deleted">已删除</option><option value="all">全部状态</option></select>
    </div>
    <p v-if="notice" class="alert success" role="status">{{notice}}</p>
    <div v-if="loadError" class="alert error" role="alert">{{loadError}}<button class="small" :disabled="listBusy" @click="loadUsers()">重新加载</button></div>
    <div class="user-table-scroll" :aria-busy="listBusy">
      <table class="user-table"><thead><tr><th scope="col">用户名</th><th scope="col">显示姓名</th><th scope="col">角色</th><th scope="col">最近登录</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead><tbody>
        <tr v-for="account in users" :key="account.id"><td><strong>{{account.username}}</strong><span v-if="account.id === currentUser.id" class="user-self">当前账号</span></td><td>{{account.display_name}}</td><td>{{roleNames[account.role]}}</td><td class="user-date">{{date(account.last_login_at)}}</td><td><span class="badge" :class="account.disabled_at ? 'ignored' : 'approved'">{{account.disabled_at ? '已删除' : '正常'}}</span></td><td><div class="user-row-actions">
          <button type="button" class="small" :aria-label="'查看账号 '+account.username" :disabled="busy || listBusy" @click="openDialog('view', account, $event)">查看</button>
          <template v-if="!account.disabled_at"><button type="button" class="small" :aria-label="'编辑账号 '+account.username" :disabled="busy || listBusy" @click="openDialog('edit', account, $event)">编辑</button><button type="button" class="small danger" :aria-label="'删除账号 '+account.username" :title="account.id === currentUser.id ? '不能删除当前登录账号' : '删除账号并保留历史记录'" :disabled="busy || listBusy || account.id === currentUser.id" @click="openDialog('delete', account, $event)">删除</button></template>
          <button v-else type="button" class="small" :aria-label="'恢复账号 '+account.username" :disabled="busy || listBusy" @click="openDialog('restore', account, $event)">恢复</button>
        </div></td></tr>
        <tr v-if="!users.length"><td colspan="6" class="user-empty">{{listBusy ? '正在读取账号…' : query || role || status !== 'active' ? '没有符合条件的账号' : '暂无账号'}}</td></tr>
      </tbody></table>
    </div>
    <Pagination :page="page" :total="total" :disabled="busy || listBusy" @change="loadUsers"/>
  </section>
  <div v-if="editor" class="modal-backdrop" @keydown.esc.prevent.stop="closeDialog()"><section class="modal user-editor-modal" role="dialog" aria-modal="true" aria-labelledby="user-editor-title">
    <div class="section-line"><h2 id="user-editor-title" ref="dialogTitle" tabindex="-1">{{titles[editor.mode]}}</h2><button type="button" class="icon-button" aria-label="关闭账号窗口" :disabled="busy" @click="closeDialog()"><X :size="18"/></button></div>
    <p v-if="formError" class="alert error" role="alert">{{formError}}</p><p v-if="reading" class="hint" role="status">正在读取账号资料…</p>
    <form v-if="['create','edit'].includes(editor.mode)" @submit.prevent="submit">
      <fieldset :disabled="busy || reading" class="user-form-fields">
        <div class="form-row"><label>用户名<input v-model="form.username" minlength="2" maxlength="100" required autocomplete="off"/></label><label>显示姓名<input v-model="form.display_name" maxlength="100" required autocomplete="off"/></label></div>
        <label>角色<select v-model="form.role" :disabled="editor.target?.id === currentUser.id"><option value="agent">客服</option><option value="reviewer">审核员</option><option value="admin">管理员</option></select></label>
        <label>{{editor.mode === 'create' ? '初始密码' : '新密码（留空保持不变）'}}<input v-model="form.password" type="password" minlength="12" maxlength="200" :required="editor.mode === 'create'" autocomplete="new-password" :placeholder="editor.mode === 'create' ? '至少12位' : '需要重设密码时填写，至少12位'"/></label>
        <p v-if="editor.mode === 'edit'" class="hint">修改用户名、角色或密码后，该账号原有登录会话将失效，需要重新登录。</p>
      </fieldset>
      <div class="actions"><button type="button" :disabled="busy" @click="closeDialog()">取消</button><button type="submit" class="primary" :disabled="busy || reading || !validForm || editor.mode === 'edit' && !editor.target">{{busy ? '正在保存…' : editor.mode === 'create' ? '创建账号' : '保存修改'}}</button></div>
    </form>
    <template v-else-if="editor.target">
      <dl v-if="editor.mode === 'view'" class="user-details"><dt>用户名</dt><dd>{{editor.target.username}}</dd><dt>显示姓名</dt><dd>{{editor.target.display_name}}</dd><dt>角色</dt><dd>{{roleNames[editor.target.role]}}</dd><dt>状态</dt><dd>{{editor.target.disabled_at ? '已删除' : '正常'}}</dd><dt>创建时间</dt><dd>{{date(editor.target.created_at)}}</dd><dt>最近登录</dt><dd>{{date(editor.target.last_login_at)}}</dd></dl>
      <template v-else><p class="user-action-name">{{editor.target.display_name}} · {{editor.target.username}}</p><p class="hint">{{editor.mode === 'delete' ? '删除后该账号将无法登录，历史工单、QA 和审核记录会保留；可在“已删除”列表中恢复。' : '恢复后该账号可重新登录，原有角色和历史记录会保留。'}}</p></template>
      <div class="actions"><button type="button" :disabled="busy" @click="closeDialog()">{{editor.mode === 'view' ? '关闭' : '取消'}}</button><button v-if="editor.mode !== 'view'" type="button" :class="editor.mode === 'delete' ? 'danger' : 'primary'" :disabled="busy || reading" @click="confirmAccountAction">{{busy ? '正在处理…' : editor.mode === 'delete' ? '确认删除账号' : '确认恢复账号'}}</button></div>
    </template>
  </section></div>
</template>
