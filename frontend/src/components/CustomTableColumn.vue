<template>
  <el-table-column :prop="prop" :label="label">
    <template #default="scope">
      <span :class="getStatusClass(scope.row[prop])">
        {{ scope.row[prop] }}
      </span>
    </template>
  </el-table-column>
</template>

<script setup lang="ts">

const props = defineProps<{
  prop: string;
  label: string;
}>();

const getStatusClass = (status: string) => {
  return {
    'fault-status': status === '故障' || status === '无效'|| status === '落下(电缆)',
    'normal-status': status === '正常',
    'jdqxq-status': status === '吸起'
  };
};
</script>

<style scoped>
.fault-status {
  color: red;
}
.normal-status {
  color: green;
}
.jdqxq-status {
  color: #409EFF;
}
</style>
