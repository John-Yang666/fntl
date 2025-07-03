<template>
  <el-container>
    <el-aside>
      <AsideComponent @device-selected="updateDeviceName"></AsideComponent>
    </el-aside>
    <el-main>
      <div>
        <!-- <h2>{{ deviceName }}</h2> 显示当前选中的设备名称 -->
        <DeviceNameComponent></DeviceNameComponent>
        <el-button @click="toggleAnalogDataChart">
          {{ showAnalogDataChart ? '关闭闭塞电压监测图' : '加载闭塞电压监测图' }}
        </el-button>
        <el-button @click="openRestartCommandWindow">发送重启网管板命令</el-button>
        <el-button class="right-button2" @click="openSwitchModeWindow">发送变更切换模式命令</el-button>
        <el-button class="right-button" @click="openInNewWindow">打开新窗口</el-button>
        <div v-if="showAnalogDataChart">
          <AnalogDataChart/>
        </div>
        <DetailedStatusComponent/>
      </div>
    </el-main>
  </el-container>
</template>

<script lang='ts' setup>
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import DetailedStatusComponent from '@/components/DetailedStatusComponent.vue';
import AsideComponent from '@/components/AsideComponent.vue';
import AnalogDataChart from '@/components/AnalogDataChart.vue';
import DeviceNameComponent from '@/components/DeviceNameComponent.vue';

const route = useRoute();
const deviceName = ref<string>(''); // 设备名称
const showAnalogDataChart = ref<boolean>(false); // 控制 AnalogDataChart 显示

const updateDeviceName = (name: string) => {
  deviceName.value = name;
};

const toggleAnalogDataChart = () => {
  showAnalogDataChart.value = !showAnalogDataChart.value;
};

// 打开新窗口
const openInNewWindow = () => {
  const url = window.location.href;
  const width = window.screen.width;
  const height = window.screen.height / 2;
  window.open(url, '_blank', `width=${width},height=${height}`);
};

// 打开切换模式窗口
const openSwitchModeWindow = () => {
  const idStr = route.params.index as string;
  const url = `${window.location.origin}/switch-mode/${idStr}`;
  window.open(url, '_blank', 'width=500,height=400');
};

//打开重启命令窗口
const openRestartCommandWindow = () => {
  const idStr = route.params.index as string;
  const url = `${window.location.origin}/restart-command/${idStr}`;
  window.open(url, '_blank', 'width=500,height=400');
};

</script>

<style scoped>
.right-button {
  position: absolute;
  right: 30px; /* 距离右边的距离，可以根据需要调整 */
}
.right-button2 {
  position: absolute;
  right: 200px; /* 距离右边的距离，可以根据需要调整 */
}
</style>