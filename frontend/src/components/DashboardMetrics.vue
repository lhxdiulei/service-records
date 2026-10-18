<script setup>
import { computed } from 'vue'
import { Tickets, BookOpen, ClipboardCheck, MessagesSquare } from 'lucide-vue-next'
const props = defineProps({ overview: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['navigate'])
const cards = computed(() => [
  { page: 'tickets', title: '服务工单', icon: Tickets, count: props.overview.tickets, description: `${props.overview.official_tickets} 张已有正式记录` },
  { page: 'qa', title: '知识 QA', icon: BookOpen, count: props.overview.official_qa, description: `${props.overview.qa} 条草稿与正式知识` },
  { page: 'reviews', title: '待审核', icon: ClipboardCheck, count: props.overview.reviews, description: '等待确认的工单与知识' },
  { page: 'messages', title: '待归属消息', icon: MessagesSquare, count: props.overview.unassigned_messages, description: '全部导入记录中待核对的消息' },
])
</script>
<template>
  <div class="metrics">
    <button v-for="card in cards" :key="card.page" type="button" class="metric metric-link" :disabled="disabled" :aria-label="'查看'+card.title" @click="!disabled && emit('navigate', card.page)">
      <span>{{card.title}}<component :is="card.icon" :size="19"/></span>
      <strong>{{card.count ?? 0}}</strong><small>{{card.description}}</small>
    </button>
  </div>
</template>
<style scoped>
.metric-link { display:block; min-width:0; width:100%; text-align:left; font:inherit; color:inherit; cursor:pointer; transition:border-color .15s,box-shadow .15s,background .15s; }
.metric-link:hover:not(:disabled) { background:#f8fbf7; border-color:#91b4a5; box-shadow:0 3px 12px #1c665b0d; }
.metric-link:focus-visible { outline:3px solid #72b6a9; outline-offset:3px; }
.metric-link:disabled { cursor:wait; }
</style>
