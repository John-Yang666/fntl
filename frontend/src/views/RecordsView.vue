<template>
  <div class="records-view">
    <el-button @click="goToAlarmData" class="equal-width-button">
      <div class="icon-wrapper"><el-icon><Bell /></el-icon>
        <span>告警记录</span>
      </div>
    </el-button>
    <el-button @click="goToRelayAction" class="equal-width-button">
      <div class="icon-wrapper"><el-icon><Switch /></el-icon>
        <span>继电器动作记录</span>
      </div>
    </el-button>
    <el-button @click="goToUserOperation" class="equal-width-button">
      <div class="icon-wrapper"><el-icon><User /></el-icon>
        <span>操作记录</span>
      </div>
    </el-button>
  </div>
</template>

<script lang="ts" setup>
//import { defineComponent } from 'vue';
import { Bell, Switch, User } from '@element-plus/icons-vue';

const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}`;

const goToAlarmData = () => {
  window.open(`${baseURL}/admin/myapp/alarmdata/`, '_blank');
};

const goToRelayAction = () => {
  window.open(`${baseURL}/admin/myapp/relayaction/`, '_blank');
};

const goToUserOperation = () => {
  window.open(`${baseURL}/admin/myapp/useroperation/`, '_blank');
};
</script>

<style scoped>
.records-view {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 50vh;
  margin-top: 30px; 
}

.equal-width-button {
  padding: 10px 20px;
  font-size: 16px;
  cursor: pointer;
  margin: 0 10px;
  width: 200px; /* 设置按钮的宽度相同 */
  height: 350px; /* Adjust height as needed */
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center; /* Center align text */
}

.equal-width-button .el-icon {
  font-size: 30px;
  margin-bottom: 10px;
}

.icon-wrapper {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}
</style>