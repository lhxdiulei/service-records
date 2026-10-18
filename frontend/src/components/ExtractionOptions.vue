<script setup>
import { computed } from 'vue'
import '../file-processing.css'

const props = defineProps({
  profiles: { type: Array, default: () => [] },
  profile: { type: String, default: 'local' },
  mode: { type: String, default: 'both' },
  disabled: Boolean,
})
const emit = defineEmits(['update:profile', 'update:mode'])
const modelName = computed(() => props.profile === 'external' ? '外部模型' : '本地模型')
const modeName = computed(() => ({ both: '工单与 QA', ticket: '仅工单', qa: '仅 QA' })[props.mode] || '工单与 QA')
const configured = computed(() => !!props.profiles.find(item => item.id === props.profile)?.configured)
const choices = computed(() => ['local', 'external'].map(id => ({ id, configured: !!props.profiles.find(item => item.id === id)?.configured })))
</script>

<template>
  <div class="extraction-options">
    <div class="extraction-options-summary">
      <span>生成选项：<strong>{{ modelName }} · {{ modeName }}</strong></span>
      <span v-if="!configured" class="warning-text">所选模型未配置</span>
    </div>
    <details class="extraction-options-details">
      <summary>调整生成选项</summary>
      <div class="extraction-options-fields">
        <label>使用模型
          <select :value="profile" :disabled="disabled" @change="emit('update:profile', $event.target.value)">
            <option v-for="item in choices" :key="item.id" :value="item.id">{{ item.id === 'local' ? '本地 / 内网模型' : '外部模型' }} · {{ item.configured ? '已配置' : '未配置' }}</option>
          </select>
        </label>
        <label>生成内容
          <select :value="mode" :disabled="disabled" @change="emit('update:mode', $event.target.value)">
            <option value="both">工单与 QA</option>
            <option value="ticket">仅工单</option>
            <option value="qa">仅 QA</option>
          </select>
        </label>
      </div>
    </details>
    <p v-if="profile === 'external'" class="extraction-options-notice">本次生成会将相关聊天原文发送到已配置的外部模型服务。</p>
    <p v-if="!configured" class="extraction-options-notice">请先配置所选模型的归属与抽取工作流，或选择已配置的模型。系统不会自动切换模型。</p>
  </div>
</template>
