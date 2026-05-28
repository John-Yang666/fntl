<template>
  <el-container>
    <el-aside>
      <AsideComponent @device-selected="updateDeviceName"></AsideComponent>
    </el-aside>
    <el-main>
      <div>
        <DeviceNameComponent></DeviceNameComponent>
        <el-button v-if="isBt" @click="toggleAnalogDataChart">
          {{ showAnalogDataChart ? '关闭闭塞电压监测图' : '加载闭塞电压监测图' }}
        </el-button>
        <el-button class="right-button2" @click="openSwitchModeWindow">
          发送远程控制命令
        </el-button>
        <el-button class="right-button" @click="openInNewWindow">打开新窗口</el-button>
        <div v-if="isBt && showAnalogDataChart">
          <AnalogDataChart/>
        </div>
        <DetailedStatusComponent v-if="isBt" />
        <SyDetailedStatusComponent v-else />
      </div>
    </el-main>
  </el-container>
</template>

<script lang='ts' setup>
import { computed, ref } from 'vue';
import { useRoute } from 'vue-router';
import DetailedStatusComponent from '@/components/DetailedStatusComponent.vue';
import AsideComponent from '@/components/AsideComponent.vue';
import AnalogDataChart from '@/components/AnalogDataChart.vue';
import DeviceNameComponent from '@/components/DeviceNameComponent.vue';
import SyDetailedStatusComponent from '@/components/SyDetailedStatusComponent.vue';
import { getSystemFromRoute } from '@/utils/systems';

const route = useRoute();
const deviceName = ref<string>('');
const showAnalogDataChart = ref<boolean>(false);
const system = computed(() => getSystemFromRoute(route.params.system));
const isBt = computed(() => system.value === 'bt');

const updateDeviceName = (name: string) => {
  deviceName.value = name;
};

const toggleAnalogDataChart = () => {
  showAnalogDataChart.value = !showAnalogDataChart.value;
};

const openInNewWindow = () => {
  const url = window.location.href;
  const width = window.screen.width;
  const height = window.screen.height / 2;
  window.open(url, '_blank', `width=${width},height=${height}`);
};

const openSwitchModeWindow = () => {
  const idStr = route.params.index as string;
  const url = `${window.location.origin}/${system.value}/switch-mode/${idStr}`;
  window.open(url, '_blank', 'width=500,height=400');
};
</script>

<style scoped>
.right-button {
  position: absolute;
  right: 30px;
}

.right-button2 {
  position: absolute;
  right: 200px;
}
</style>
