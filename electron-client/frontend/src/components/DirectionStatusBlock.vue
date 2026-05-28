<template>
  <div>
    <h3>{{ directionLabel }}方向单板状态</h3>
    <BoardStatusComponent :boards="boards" />

    <el-divider />

    <h3>{{ directionLabel }}方向设备主要状态信息</h3>
    <el-button @click="emit('update:showNeighbor', !showNeighbor)">
      {{ showNeighbor ? '隐藏邻站信息' : '显示邻站信息' }}
    </el-button>
    <el-table :data="mainStatus" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="站间A通道" />
      <CustomTableColumn prop="Status2" label="站间B通道" />
      <CustomTableColumn prop="Status3" label="CPU板A通信" />
      <CustomTableColumn prop="Status4" label="CPU板B通信" />
      <CustomTableColumn prop="Status5" label="QHJ" />
      <CustomTableColumn prop="Status52" label="电缆状态" />
      <CustomTableColumn prop="Status6" label="切换模式" />
      <template v-if="showNeighbor">
        <CustomTableColumn prop="Status7" label="邻站QHJ" />
        <CustomTableColumn prop="Status72" label="邻站电缆状态" />
        <CustomTableColumn prop="Status8" label="邻站切换模式" />
      </template>
    </el-table>

    <h3>{{ directionLabel }}方向动作继电器状态信息</h3>
    <h4>A系</h4>
    <el-table :data="relayStatusA" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="本站ZDJ" />
      <CustomTableColumn prop="Status2" label="本站FDJ" />
      <CustomTableColumn prop="Status3" label="本站ZXJ" />
      <CustomTableColumn prop="Status4" label="本站FXJ" />
      <template v-if="showNeighbor">
        <CustomTableColumn prop="Status5" label="邻站ZDJ" />
        <CustomTableColumn prop="Status6" label="邻站FDJ" />
        <CustomTableColumn prop="Status7" label="邻站ZXJ" />
        <CustomTableColumn prop="Status8" label="邻站FXJ" />
      </template>
    </el-table>

    <h4>B系</h4>
    <el-table :data="relayStatusB" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="本站ZDJ" />
      <CustomTableColumn prop="Status2" label="本站FDJ" />
      <CustomTableColumn prop="Status3" label="本站ZXJ" />
      <CustomTableColumn prop="Status4" label="本站FXJ" />
      <template v-if="showNeighbor">
        <CustomTableColumn prop="Status5" label="邻站ZDJ" />
        <CustomTableColumn prop="Status6" label="邻站FDJ" />
        <CustomTableColumn prop="Status7" label="邻站ZXJ" />
        <CustomTableColumn prop="Status8" label="邻站FXJ" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { defineProps, defineEmits } from 'vue';
import type { Board } from '../utils/types';
import CustomTableColumn from './CustomTableColumn.vue';
import BoardStatusComponent from './BoardStatusComponent.vue';

const props = defineProps<{
  direction: string;
  boards: Board[];
  mainStatus: Record<string, string>[];
  relayStatusA: Record<string, string>[];
  relayStatusB: Record<string, string>[];
  showNeighbor: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:showNeighbor', value: boolean): void;
}>();

const directionLabel = props.direction === '1' ? '一' : '二';
</script>

<style scoped>
h3 {
  margin-top: 20px;
}
</style>
