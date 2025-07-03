<template>
  <el-row class="board-status" :gutter="12">
    <el-col :span="4" v-for="board in boards" :key="board.name">
      <el-card :body-style="{ padding: '16px' }">
        <h5 style="text-align: center; margin-bottom: 12px">{{ board.name }}</h5>
        <div
          :class="{
            'status-indicator': true,
            'is-good': goodStatus.has(board.status),
            'is-bad': board.status === '故障',
            'is-null': board.status === 'null'
          }"
        >
          {{ board.status }}
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
interface Board {
  name: string;
  status: '备用' | '主用' | '正常' | '故障' | 'null';
}

const props = defineProps<{ boards: Board[] }>();

const goodStatus = new Set(['正常', '主用', '备用']);
</script>

<style scoped>
.status-indicator {
  padding: 10px;
  color: white;
  text-align: center;
  border-radius: 4px;
  font-weight: bold;
  font-size: 14px;
}
.is-good {
  background-color: #67C23A;
}
.is-bad {
  background-color: #F56C6C;
}
.is-null {
  background-color: #909399;
}
</style>
