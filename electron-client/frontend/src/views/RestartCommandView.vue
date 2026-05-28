<template>
  <div v-if="isBt">
    <RestartCommandComponent />
  </div>
  <div v-else class="unsupported">
    SY 设备不支持该窗口，请在“发送远程控制命令”窗口中操作。
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import RestartCommandComponent from '@/components/RestartCommandComponent.vue';
import { getSystemFromRoute } from '@/utils/systems';

const route = useRoute();
const isBt = computed(() => getSystemFromRoute(route.params.system) === 'bt');
</script>

<style scoped>
.unsupported {
  padding: 32px;
  text-align: center;
  font-size: 16px;
}
</style>
