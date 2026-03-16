<template>
  <div>
    <SwitchModeComponent v-if="isBt" />
    <SySwitchModeComponent v-else />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import SwitchModeComponent from '@/components/SwitchModeComponent.vue';
import SySwitchModeComponent from '@/components/SySwitchModeComponent.vue';
import { getSystemFromRoute } from '@/utils/systems';

const route = useRoute();
const isBt = computed(() => getSystemFromRoute(route.params.system) === 'bt');
</script>

<style scoped>
</style>
