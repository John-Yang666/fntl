<template>
  <div>
    <!-- 当路径不是 '/login' 或 '/switch-mode/:index' 或 '/restart-command/:index' 时才显示 HeaderComponent -->
    <HeaderComponent v-if="!hideHeader" />
    <router-view></router-view>
  </div>
</template>

<script lang="ts" setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import HeaderComponent from '@/components/HeaderComponent.vue';

// 获取当前路由
const route = useRoute();

// 计算属性：判断当前路径是否需要隐藏 HeaderComponent
const hideHeader = computed(() => {
  const hidePaths = ['/switch-mode', '/restart-command'];
  // 检查当前路径是否以这些路径开头
  return hidePaths.some(path => route.path.startsWith(path));
});
</script>