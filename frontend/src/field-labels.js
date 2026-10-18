// Shared by editor selectors and API validation messages.
export const fieldLabels = Object.freeze({
  title: '工单标题', problem: '问题内容', impact: '影响范围',
  handling_summary: '处理过程', current_conclusion: '当前结论', status: '处理状态',
  question: '问题', answer: '回答', answer_state: '答案状态', applicability: '适用条件',
  claims: '关键事实与依据', answer_claims: '关键事实与依据', claim_key: '事实编号', text: '内容',
  contributors: '核心贡献者', contribution: '贡献说明', participant_id: '核心贡献者',
  evidence: '原文依据', evidence_span_id: '原文依据', evidence_span_ids: '原文依据',
  field_key: '引用用于说明', relation: '证据关系', next_actions: '后续待办', basis: '待办依据',
  first_visible_message_id: '首次可见消息', first_question_message_id: '原始提问消息', date_basis: '日期依据',
  message_id: '来源聊天', exact_excerpt: '引用原文', occurrence: '原文出现次数',
  username: '用户名', display_name: '显示姓名', password: '密码', role: '角色',
  comment: '审核意见', change_reason: '修改说明',
})

export function fieldLabel(key) { return fieldLabels[key] || '填写内容' }

function validationPath(loc = []) {
  return loc.filter(key => !['body', 'content', 'query', 'path'].includes(key))
    .map(key => Number.isInteger(key) ? `第 ${key + 1} 项` : fieldLabel(key)).join(' · ') || '填写内容'
}
function validationReason(error) {
  const length = error.ctx?.min_length ?? error.ctx?.max_length
  if (error.type === 'missing') return '请填写此项'
  if (error.type === 'string_too_short') return `至少填写 ${length} 个字符`
  if (error.type === 'string_too_long') return `最多填写 ${length} 个字符`
  if (error.type === 'too_short') return `至少添加 ${length} 项`
  if (error.type === 'too_long') return `最多添加 ${length} 项`
  if (error.type === 'literal_error' || error.type === 'enum') return '请选择有效选项'
  if (error.type?.startsWith('uuid')) return '请选择有效记录'
  return '格式不正确，请检查此项'
}

export function apiErrorMessage(detail, status) {
  if (typeof detail?.message === 'string' && detail.message) return detail.message
  if (Array.isArray(detail)) return detail.map(error => `${validationPath(error.loc)}：${validationReason(error)}`).join('；')
  return `请求失败 (${status})`
}
