<script setup>
defineProps({ reviews: { type: Array, default: () => [] }, busy: Boolean })
defineEmits(['open-revision'])
const actions = { submit: '提交审核', approve: '批准', reject: '驳回' }
function date(value) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
</script>

<template>
  <article v-for="review in reviews" :key="review.id" class="review-history-entry">
    <div class="review-history-heading"><span class="badge" :class="review.action === 'approve' ? 'approved' : review.action === 'reject' ? 'rejected' : 'in_review'">{{ actions[review.action] || review.action }}</span><strong>{{ review.actor_name || review.actor_username || '未知账号' }}<span v-if="review.actor_username && review.actor_username !== review.actor_name">（{{ review.actor_username }}）</span></strong><button type="button" class="text-button" :disabled="busy || !review.revision_id" @click="$emit('open-revision', review.revision_id)">版本 {{ review.revision_no ?? '待确认' }}</button><small>{{ date(review.created_at) }}</small></div>
    <p>{{ review.reason || '无附加意见' }}</p>
  </article>
</template>
