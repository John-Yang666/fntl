<template>
  <el-container>
    <el-aside>
      <AsideComponent></AsideComponent>
    </el-aside>
    <el-main>
      <div>
        <h1>设备总览</h1>
        <!-- 在拓扑图上方添加设备筛选组件 -->
        <TopologyGraph />
        <DeviceFilter />
      </div>
    </el-main>
  </el-container>
</template>

<script lang="ts" setup>
import AsideComponent from '@/components/AsideComponent.vue';
import TopologyGraph from './TopologyGraph.vue';
import DeviceFilter from '@/components/DeviceFilter.vue';  // 引入 DeviceFilter 组件

</script>