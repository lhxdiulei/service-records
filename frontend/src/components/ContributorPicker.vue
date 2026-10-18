<script setup>
import { computed, ref } from 'vue'
import SearchSelect from './SearchSelect.vue'
import { contributorCandidates } from '../editor-assist.js'
import '../contributor-picker.css'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  bindings: { type: Array, default: () => [] },
  messages: { type: Array, default: () => [] },
  participants: { type: Array, default: () => [] },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue', 'locate'])
const selectedId = ref(''), explanation = ref('提供关键解答')
const candidates = computed(() => contributorCandidates(props.bindings, props.messages, props.participants))
const candidateById = computed(() => new Map(candidates.value.map(item => [String(item.participant_id), item])))
const suggestions = computed(() => {
  const selected = new Set(props.modelValue.map(item => String(item.participant_id)))
  return candidates.value.filter(item => !selected.has(String(item.participant_id)))
})
const options = computed(() => suggestions.value.map(item => ({
  value: item.participant_id, label: item.display_name,
  description: item.excerpts.join('；'),
})))
const selectedCandidate = computed(() => suggestions.value.find(item => String(item.participant_id) === String(selectedId.value)))
const cloneContributors = () => props.modelValue.map(item => ({ ...item, evidence_span_ids: [...(item.evidence_span_ids || [])] }))

function displayName(item) {
  return props.participants.find(person => String(person.id) === String(item.participant_id))?.display_name
    || candidateById.value.get(String(item.participant_id))?.display_name
    || props.messages.find(message => String(message.sender_participant_id) === String(item.participant_id))?.sender_name_raw
    || '未确认成员'
}
function needsVerification(item) {
  const candidate = candidateById.value.get(String(item.participant_id))
  const validIds = new Set((candidate?.evidence_span_ids || []).map(String))
  return !item.evidence_span_ids?.length || item.evidence_span_ids.some(id => !validIds.has(String(id)))
}
function evidenceFor(item) {
  return [...new Set(item.evidence_span_ids || [])].map(id => props.bindings.find(binding => String(binding.evidence_span_id) === String(id)))
    .filter(binding => binding && binding.message_id && Number.isInteger(binding.start_cp) && Number.isInteger(binding.end_cp) && binding.start_cp >= 0 && binding.end_cp > binding.start_cp)
}
function locate(binding) {
  if (!props.disabled) emit('locate', { message_id: binding.message_id, start_cp: binding.start_cp, end_cp: binding.end_cp })
}
function updateContribution(index, value) {
  if (props.disabled) return
  const next = cloneContributors()
  next[index].contribution = value
  emit('update:modelValue', next)
}
function removeContributor(index) {
  if (props.disabled) return
  const next = cloneContributors()
  next.splice(index, 1)
  emit('update:modelValue', next)
}
function addCandidates(items, contribution) {
  if (props.disabled || !items.length) return
  const next = cloneContributors()
  const existingIds = new Set(next.map(item => String(item.participant_id)))
  for (const item of items) {
    if (existingIds.has(String(item.participant_id))) continue
    next.push({
      participant_id: item.participant_id,
      contribution: contribution || item.contribution,
      evidence_span_ids: [...item.evidence_span_ids],
    })
    existingIds.add(String(item.participant_id))
  }
  emit('update:modelValue', next)
}
function addSelected() {
  if (!selectedCandidate.value || !explanation.value.trim()) return
  addCandidates([selectedCandidate.value], explanation.value.trim())
  selectedId.value = ''; explanation.value = '提供关键解答'
}
</script>

<template>
  <section class="contributor-picker" aria-label="核心贡献者" @input.stop @change.stop>
    <div class="contributor-picker__heading"><h3>核心贡献者</h3><span v-if="modelValue.length">已确认 {{ modelValue.length }} 人</span></div>
    <p class="contributor-picker__hint">根据支持回答的本人发言提供建议，采用后才会保存。引用或转述不能作为本人的贡献。</p>

    <div v-for="(item, index) in modelValue" :key="item.participant_id" class="contributor-picker__member">
      <div class="contributor-picker__member-row">
        <strong>{{ displayName(item) }}</strong>
        <label class="contributor-picker__contribution">贡献说明
          <input :value="item.contribution" :disabled="disabled" :aria-label="`${displayName(item)}的贡献说明`" placeholder="说明此人的贡献" @input="updateContribution(index, $event.target.value)">
        </label>
        <button type="button" class="small" :disabled="disabled" :aria-label="`移除贡献者${displayName(item)}`" @click="removeContributor(index)">移除</button>
      </div>
      <p v-if="needsVerification(item)" class="contributor-picker__warning">当前回答依据尚不能完整确认这名贡献者，请核对原文。已保留原有贡献说明和证据。</p>
      <details v-if="evidenceFor(item).length" class="contributor-picker__evidence">
        <summary>查看依据（{{ evidenceFor(item).length }}）</summary>
        <button v-for="binding in evidenceFor(item)" :key="binding.evidence_span_id" type="button" :disabled="disabled" @click="locate(binding)">
          <span>{{ binding.excerpt || '定位这段原文' }}</span><span>定位原文 →</span>
        </button>
      </details>
      <p v-else class="contributor-picker__hint">原有证据未包含在当前字段依据中，请结合原始聊天核对。</p>
    </div>

    <div v-if="suggestions.length" class="contributor-picker__suggestions">
      <div class="contributor-picker__suggestion-row">
        <p>根据回答依据建议：<strong>{{ suggestions.map(item => item.display_name).join('、') }}</strong></p>
        <button type="button" class="small" :disabled="disabled" @click="addCandidates(suggestions)">采用建议{{ suggestions.length > 1 ? `（${suggestions.length} 人）` : '' }}</button>
      </div>
      <details class="contributor-picker__manual">
        <summary>手动补充贡献者</summary>
        <p class="contributor-picker__hint">可逐个选择有本人直接回答依据的成员，并补充贡献说明。</p>
        <div class="contributor-picker__manual-row">
          <SearchSelect v-model="selectedId" :options="options" :disabled="disabled" aria-label="待补充贡献者" placeholder="选择有回答依据的成员"/>
          <input v-model="explanation" :disabled="disabled" aria-label="新增贡献者的贡献说明" placeholder="贡献说明">
          <button type="button" class="small" :disabled="disabled || !selectedCandidate || !explanation.trim()" @click="addSelected">添加</button>
        </div>
        <blockquote v-if="selectedCandidate">{{ selectedCandidate.excerpts.join('；') }}</blockquote>
      </details>
    </div>
    <p v-else-if="!modelValue.length" class="contributor-picker__empty">暂未找到可建议的贡献者。请先为回答或关键事实绑定本人直接发言的原文依据。</p>
  </section>
</template>
