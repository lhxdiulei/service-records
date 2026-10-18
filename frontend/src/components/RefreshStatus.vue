<script setup>
import { RefreshCw } from 'lucide-vue-next'
defineProps({ error: { type: String, default: '' }, lastSuccess: { type: String, default: '' }, busy: Boolean })
defineEmits(['retry'])
function date(value) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
</script>

<template>
  <div class="refresh-status" :class="{ 'refresh-status-failed': error }" :role="error ? 'alert' : 'status'">
    <div>
      <p v-if="error"><strong>更新失败</strong>：{{ error }}。当前展示的进度可能已过期。</p>
      <small>{{ lastSuccess ? `最后成功更新：${date(lastSuccess)}` : '尚未成功获取最新进度' }}</small>
    </div>
    <button v-if="error" type="button" class="small" :disabled="busy" @click="$emit('retry')"><RefreshCw :size="14"/>{{ busy ? '正在重试…' : '重试更新' }}</button>
  </div>
</template>
