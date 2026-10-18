<script setup>
import { computed, ref, watch } from 'vue'
import Pagination from './Pagination.vue'
const props = defineProps({ warnings: { type: Array, default: () => [] }, busy: Boolean, focusedIndex: { type: Number, default: null } })
defineEmits(['locate'])
const page = ref(1)
const visible = computed(() => props.warnings.slice((page.value - 1) * 10, page.value * 10))
watch(() => props.warnings.length, total => { page.value = Math.min(page.value, Math.max(1, Math.ceil(total / 10))) })
</script>

<template>
  <details v-if="warnings.length" class="import-warnings">
    <summary>发现 {{ warnings.length }} 项解析警告<span>展开查看全部警告及对应原文</span></summary>
    <ol class="import-warning-list" :start="(page - 1) * 10 + 1">
      <li v-for="(warning, index) in visible" :key="`${page}-${index}`" :class="{ 'warning-selected': focusedIndex === warning.index }">
        <div><strong>第 {{ warning.index + 1 }} 条消息<span v-if="warning.source_line_start"> · 原文第 {{ warning.source_line_start }}<template v-if="warning.source_line_end > warning.source_line_start">–{{ warning.source_line_end }}</template> 行</span></strong><p>{{ warning.message }}</p></div>
        <button type="button" class="small" :disabled="busy" @click="$emit('locate', warning)">定位原文</button>
      </li>
    </ol>
    <Pagination v-if="warnings.length > 10" :page="page" :total="warnings.length" :disabled="busy" @change="page = $event"/>
  </details>
</template>
