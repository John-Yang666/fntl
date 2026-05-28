<template>
  <div>
    <el-button @click="toggleCollapse1">
      {{ isCollapsed1 ? '显示一方向信息' : '隐藏一方向信息' }}
    </el-button>
    <el-button @click="toggleCollapse2">
    {{ isCollapsed2 ? '显示二方向信息' : '隐藏二方向信息' }}
  </el-button>
  </div>
  <template v-if="!isCollapsed1">
  <div>
    <h3>一方向单板状态</h3>
    <BoardStatusComponent :boards="boards1" />
  </div>
  <el-divider />
  <div>
    <h3>一方向设备主要状态信息</h3>
    <el-button @click="showNeighbor = !showNeighbor">
     {{ showNeighbor ? '显示邻站信息' : '隐藏邻站信息' }}
    </el-button>
    <el-table :data="direction1MainStatus" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="站间A通道" />
      <CustomTableColumn prop="Status2" label="站间B通道" />
      <CustomTableColumn prop="Status3" label="CPU板A通信" />
      <CustomTableColumn prop="Status4" label="CPU板B通信" />
      <CustomTableColumn prop="Status5" label="QHJ" />
      <CustomTableColumn prop="Status52" label="电缆状态" />
      <CustomTableColumn prop="Status6" label="切换模式" />
      <template v-if="!showNeighbor">
        <CustomTableColumn prop="Status7" label="邻站QHJ" />
        <CustomTableColumn prop="Status72" label="邻站电缆状态" />
        <CustomTableColumn prop="Status8" label="邻站切换模式" />
      </template>
    </el-table>
 
    <h3>一方向动作继电器状态信息</h3>
    <h4>A系</h4>
    <el-table :data="direction1RelayStatusA" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="本站ZDJ" />
      <CustomTableColumn prop="Status2" label="本站FDJ" />
      <CustomTableColumn prop="Status3" label="本站ZXJ" />
      <CustomTableColumn prop="Status4" label="本站FXJ" />
      <template v-if="!showNeighbor">
      <CustomTableColumn prop="Status5" label="邻站ZDJ" />
      <CustomTableColumn prop="Status6" label="邻站FDJ" />
      <CustomTableColumn prop="Status7" label="邻站ZXJ" />
      <CustomTableColumn prop="Status8" label="邻站FXJ" />
    </template>
    </el-table>
    <h4>B系</h4>
    <el-table :data="direction1RelayStatusB" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="本站ZDJ" />
      <CustomTableColumn prop="Status2" label="本站FDJ" />
      <CustomTableColumn prop="Status3" label="本站ZXJ" />
      <CustomTableColumn prop="Status4" label="本站FXJ" />
      <template v-if="!showNeighbor">
      <CustomTableColumn prop="Status5" label="邻站ZDJ" />
      <CustomTableColumn prop="Status6" label="邻站FDJ" />
      <CustomTableColumn prop="Status7" label="邻站ZXJ" />
      <CustomTableColumn prop="Status8" label="邻站FXJ" />
      </template>
    </el-table>
  </div>
  <el-divider />
</template>
<template v-if="!isCollapsed2">
  <div>
    <h3>二方向单板状态</h3>
    <BoardStatusComponent :boards="boards2" />
  </div>
  <el-divider />
  <div>
    <h3>二方向设备主要状态信息</h3>
    <el-button @click="showNeighbor = !showNeighbor">
     {{ showNeighbor ? '显示邻站信息' : '隐藏邻站信息' }}
    </el-button>
    <el-table :data="direction2MainStatus" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="站间A通道" />
      <CustomTableColumn prop="Status2" label="站间B通道" />
      <CustomTableColumn prop="Status3" label="CPU板A通信" />
      <CustomTableColumn prop="Status4" label="CPU板B通信" />
      <CustomTableColumn prop="Status5" label="QHJ" />
      <CustomTableColumn prop="Status52" label="电缆状态" />
      <CustomTableColumn prop="Status6" label="切换模式" />
      <template v-if="!showNeighbor">
      <CustomTableColumn prop="Status7" label="邻站QHJ" />
      <CustomTableColumn prop="Status52" label="邻站电缆状态" />
      <CustomTableColumn prop="Status8" label="邻站切换模式" />
      </template>
    </el-table>
    <h3>二方向动作继电器状态信息</h3>
    <h4>A系</h4>
    <el-table :data="direction2RelayStatusA" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="本站ZDJ" />
      <CustomTableColumn prop="Status2" label="本站FDJ" />
      <CustomTableColumn prop="Status3" label="本站ZXJ" />
      <CustomTableColumn prop="Status4" label="本站FXJ" />
      <template v-if="!showNeighbor">
      <CustomTableColumn prop="Status5" label="邻站ZDJ" />
      <CustomTableColumn prop="Status6" label="邻站FDJ" />
      <CustomTableColumn prop="Status7" label="邻站ZXJ" />
      <CustomTableColumn prop="Status8" label="邻站FXJ" />
      </template>
    </el-table>
    <h4>B系</h4>
    <el-table :data="direction2RelayStatusB" style="width: 100%" border>
      <CustomTableColumn prop="Status1" label="本站ZDJ" />
      <CustomTableColumn prop="Status2" label="本站FDJ" />
      <CustomTableColumn prop="Status3" label="本站ZXJ" />
      <CustomTableColumn prop="Status4" label="本站FXJ" />
      <template v-if="!showNeighbor">
      <CustomTableColumn prop="Status5" label="邻站ZDJ" />
      <CustomTableColumn prop="Status6" label="邻站FDJ" />
      <CustomTableColumn prop="Status7" label="邻站ZXJ" />
      <CustomTableColumn prop="Status8" label="邻站FXJ" />
     </template>
    </el-table>
  </div>
</template>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import { useRoute } from 'vue-router';
import axios from 'axios';
import CustomTableColumn from './CustomTableColumn.vue';
import BoardStatusComponent from './BoardStatusComponent.vue';

// 动态获取当前浏览器地址栏的 IP 或域名
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;

const route = useRoute();
const device_id = ref<number>(parseInt(Array.isArray(route.params.index) ? route.params.index[0] : route.params.index, 10));

const showNeighbor = ref<boolean>(true);

const isCollapsed1 = ref<boolean>(false);
const isCollapsed2 = ref<boolean>(false);

const getCollapseStateKey = (id: number | null, stateName: string) => `isCollapsedState_${id}_${stateName}`;

const toggleCollapse1 = () => {
  if (device_id.value !== null) {
    isCollapsed1.value = !isCollapsed1.value;
    localStorage.setItem(getCollapseStateKey(device_id.value, '1'), JSON.stringify(isCollapsed1.value));
  }
};

const toggleCollapse2 = () => {
  if (device_id.value !== null) {
    isCollapsed2.value = !isCollapsed2.value;
    localStorage.setItem(getCollapseStateKey(device_id.value, '2'), JSON.stringify(isCollapsed2.value));
  }
};

const fetchCollapseState = () => {
  if (device_id.value !== null) {
    const savedState1 = localStorage.getItem(getCollapseStateKey(device_id.value, '1'));
    isCollapsed1.value = savedState1 !== null ? JSON.parse(savedState1) : false;

    const savedState2 = localStorage.getItem(getCollapseStateKey(device_id.value, '2'));
    isCollapsed2.value = savedState2 !== null ? JSON.parse(savedState2) : false;
  }
};

// 定义一个接口用于描述单个板卡的属性（在父组件中调用同一个子组件两次时，只需要定义一个 interface，因为 interface 是用来描述对象的结构的，无论你调用多少次子组件，数据结构是相同的。）
interface Board {
  name: string;
  status:  '备用'| '主用'| '正常' | '故障' | 'null';
}

// 定义两个 ref 变量分别存储两个方向的面板状态数据
const boards1 = ref<Board[]>([
  { name: '电源板A', status: 'null' },
  { name: '通信板A', status: 'null' },
  { name: '通信板B', status: 'null' },
  { name: 'CPU板A', status: 'null' },
  { name: 'CPU板B', status: 'null' },
  { name: '电源板B', status: 'null' }
]);

const boards2 = ref<Board[]>([
  { name: '电源板A', status: 'null' },
  { name: '通信板A', status: 'null' },
  { name: '通信板B', status: 'null' },
  { name: 'CPU板A', status: 'null' },
  { name: 'CPU板B', status: 'null' },
  { name: '电源板B', status: 'null' }
]);

const binaryStatus = ref<string>('');
const error = ref<string | null>(null);
//const bitIndex = ref<number>(0);
//const bitValue = ref<string | null>(null);

const direction1MainStatus = ref([
  {//大括号中为第一个对象，可以添加大括号添加对象。此对象为direction1MainStatus.value[0]
    Status1: 'null',
    Status2: 'null',
    Status3: 'null',
    Status4: 'null',
    Status5: 'null',
    Status52: 'null',
    Status6: 'null',
    Status7: 'null',
    Status72: 'null',
    Status8: 'null',
  },
]);

  const direction1RelayStatusA = ref([
  {
    Status1: 'null',
    Status2: 'null',
    Status3: 'null',
    Status4: 'null',
    Status5: 'null',
    Status6: 'null',
    Status7: 'null',
    Status8: 'null',
  },
]);

  const direction1RelayStatusB = ref([
  {
    Status1: 'null',
    Status2: 'null',
    Status3: 'null',
    Status4: 'null',
    Status5: 'null',
    Status6: 'null',
    Status7: 'null',
    Status8: 'null',
  },
]);

  const direction2MainStatus = ref([
  {
    Status1: 'null',
    Status2: 'null',
    Status3: 'null',
    Status4: 'null',
    Status5: 'null',
    Status52: 'null',
    Status6: 'null',
    Status7: 'null',
    Status72: 'null',
    Status8: 'null',
  },
]);

  const direction2RelayStatusA = ref([
  {
    Status1: 'null',
    Status2: 'null',
    Status3: 'null',
    Status4: 'null',
    Status5: 'null',
    Status6: 'null',
    Status7: 'null',
    Status8: 'null',
  },
]);

  const direction2RelayStatusB = ref([
  {
    Status1: 'null',
    Status2: 'null',
    Status3: 'null',
    Status4: 'null',
    Status5: 'null',
    Status6: 'null',
    Status7: 'null',
    Status8: 'null',
  },
]);

const getChar = (charIndex: number): string | null => {//从左到右，从4开始，和协议中字节序号一致
  // 计算实际的起始索引
  const startIndex = (charIndex - 4) * 8;

  // 确保 binaryStatus.value 存在，并且起始索引在有效范围内
  if (binaryStatus.value && startIndex >= 0 && startIndex + 8 <= binaryStatus.value.length) {
    // 提取从 startIndex 开始的八位字符
    return binaryStatus.value.slice(startIndex, startIndex + 8);
  }

  // 如果条件不满足，返回 null
  return null;
};

//从一个字节的数据中获取指定位上的字符（位序号：7、6、5、4、3、2、1、0）
const getBitValueFromChar = (char: string, bitIndex: number): string => {
  if (char && bitIndex >= 0 && bitIndex < 8) {
    return char[7 - bitIndex];
  }
  return '0';
};

const fetchSwitchStatus = async () => {//从开关量二进制数据中提取前端显示所需的数据，对上述响应式数据进行更新
  try {
    const response = await axios.get(`${baseURL}/switch-status/${device_id.value}/`);
    const base64Status = response.data.switch_status;
    // 解码 Base64 并转换为二进制字符串
    const byteArray = Uint8Array.from(atob(base64Status), c => c.charCodeAt(0));
    const binaryStatusString = Array.from(byteArray).map(byte => byte.toString(2).padStart(8, '0')).join('');
    binaryStatus.value = binaryStatusString;
    error.value = null;

    // 提取状态码中的信息
    //一方向
    let char = getChar(4);//电源板状态、CPU板通信状态
    if (char) {
      boards1.value[0].status = getBitValueFromChar(char, 0) === '0'? '正常' : '故障';
      boards1.value[5].status = getBitValueFromChar(char, 1) === '0'? '正常' : '故障';
      direction1MainStatus.value[0].Status3 = getBitValueFromChar(char, 4) === '0' ? '正常' : '故障';
      direction1MainStatus.value[0].Status4 = getBitValueFromChar(char, 5) === '0' ? '正常' : '故障';
    }

    char = getChar(7);//一方向QHJ、切换模式
    if (char) {
      direction1MainStatus.value[0].Status5 = getBitValueFromChar(char, 0) === '0' ? '落下(电缆)' : '吸起(光缆)';
      direction1MainStatus.value[0].Status52 = getBitValueFromChar(char, 1) === '0' ? '正常' : '故障';
      let switchStatus0 = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2)
      if (switchStatus0 == '00')
        direction1MainStatus.value[0].Status6 = '无效';
      else if (switchStatus0 == '01')
        direction1MainStatus.value[0].Status6 = '强制电缆';
      else if (switchStatus0 == '10')
        direction1MainStatus.value[0].Status6 = '自动';
      else if (switchStatus0 == '11')
        direction1MainStatus.value[0].Status6 = '强制光缆';
    }

    char = getChar(9);//一方向邻站QHJ、邻站切换模式
    if (char) {
      direction1MainStatus.value[0].Status7 = getBitValueFromChar(char, 0) === '0' ? '落下(电缆)' : '吸起(光缆)';
      direction1MainStatus.value[0].Status72 = getBitValueFromChar(char, 1) === '0' ? '正常' : '故障';
      let switchStatus0 = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2)
      if (switchStatus0 == '00')
        direction1MainStatus.value[0].Status8 = '无效';
      else if (switchStatus0 == '01')
        direction1MainStatus.value[0].Status8 = '强制电缆';
      else if (switchStatus0 == '10')
        direction1MainStatus.value[0].Status8 = '自动';
      else if (switchStatus0 == '11')
        direction1MainStatus.value[0].Status8 = '强制光缆';
    }

    //判定CPU工作状态（这一步得放在某些需要知道CPU状态的操作前面）
    const workingCPU = ref<string>('');//记录哪个CPU（系）为主用
    
    char = getChar(19);//一方向A系工作状态
    if (char) {
      let boardStatus = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2) + getBitValueFromChar(char, 1) + getBitValueFromChar(char, 0)
      if (boardStatus == '1010') {
        boards1.value[3].status = '主用';
        workingCPU.value = 'A'
      }
      else if (boardStatus == '0101') {
        boards1.value[3].status = '备用';
      }
      else if (boardStatus == '1001') {
        boards1.value[3].status = '故障';
      }
      else {
        boards1.value[3].status = '正常';
      }
    }

    char = getChar(28);//一方向B系工作状态
    if (char) {
      let boardStatus = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2) + getBitValueFromChar(char, 1) + getBitValueFromChar(char, 0)
      if (boardStatus == '1010'){
        boards1.value[4].status = '主用';
        workingCPU.value = 'B'
      }
      else if (boardStatus == '0101'){
        boards1.value[4].status = '备用';
      }
      else if (boardStatus == '1001'){
        boards1.value[4].status = '故障';
      }
      else{
        boards1.value[4].status = '正常';
      }
    }

    /*if (workingCPU.value == 'A') {
      char = getChar(16);//一方向CPU_A传的通信板A和B状态、站间通道故障
    }
    else if (workingCPU.value == 'B') {
      char = getChar(25);//一方向CPU_B传的……
    }
    if(char) {
      boards1.value[1].status = (getBitValueFromChar(char, 2) === '0') ? '正常' : '故障';//通信板A
      boards1.value[2].status = (getBitValueFromChar(char, 4) === '0') ? '正常' : '故障';//通信板B
      direction1MainStatus.value[0].Status1 = getBitValueFromChar(char, 2) === '0' ? '正常' : '故障';
      direction1MainStatus.value[0].Status2 = getBitValueFromChar(char, 4) === '0' ? '正常' : '故障';
    }*///20250421 bug修复：上面这段代码在宝鸡现场取值错误，改为下面的代码

    const char16 = getChar(16);
    const char25 = getChar(25);
    if(char16 && char25) {
      const d1communicationStatusA = getBitValueFromChar(char16, 2)  === '0'|| getBitValueFromChar(char25, 2) === '0';
      const d1communicationStatusB = getBitValueFromChar(char16, 4)  === '0'|| getBitValueFromChar(char25, 4) === '0';
      boards1.value[1].status = (d1communicationStatusA) ? '正常' : '故障';//通信板A
      boards1.value[2].status = (d1communicationStatusB) ? '正常' : '故障';//通信板B
      direction1MainStatus.value[0].Status1 = (d1communicationStatusA) ? '正常' : '故障';//站间A通道
      direction1MainStatus.value[0].Status2 = (d1communicationStatusB) ? '正常' : '故障';//站间B通道
    }
    
    char = getChar(14);//一方向A系报的继电器状态
    if (char) {
      direction1RelayStatusA.value[0].Status1 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction1RelayStatusA.value[0].Status2 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction1RelayStatusA.value[0].Status3 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction1RelayStatusA.value[0].Status4 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

    char = getChar(22);//一方向A系报的邻站继电器状态
    if (char) {
      direction1RelayStatusA.value[0].Status5 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction1RelayStatusA.value[0].Status6 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction1RelayStatusA.value[0].Status7 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction1RelayStatusA.value[0].Status8 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

    char = getChar(23);//一方向B系报的继电器状态
    if (char) {
      direction1RelayStatusB.value[0].Status1 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction1RelayStatusB.value[0].Status2 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction1RelayStatusB.value[0].Status3 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction1RelayStatusB.value[0].Status4 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

    char = getChar(31);//一方向B系报的邻站继电器状态
    if (char) {
      direction1RelayStatusB.value[0].Status5 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction1RelayStatusB.value[0].Status6 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction1RelayStatusB.value[0].Status7 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction1RelayStatusB.value[0].Status8 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

    //二方向（备注不清处参考一方向备注）
    char = getChar(4);
    if (char) {
      boards2.value[0].status = getBitValueFromChar(char, 2) === '0'? '正常' : '故障';
      boards2.value[5].status = getBitValueFromChar(char, 3) === '0'? '正常' : '故障';
      direction2MainStatus.value[0].Status3 = getBitValueFromChar(char, 6) === '0' ? '正常' : '故障';
      direction2MainStatus.value[0].Status4 = getBitValueFromChar(char, 7) === '0' ? '正常' : '故障';
    }

    char = getChar(11);//二方向QHJ、切换模式
    if (char) {
      direction2MainStatus.value[0].Status5 = getBitValueFromChar(char, 0) === '0' ? '落下(电缆)' : '吸起(光缆)';
      direction2MainStatus.value[0].Status52 = getBitValueFromChar(char, 1) === '0' ? '正常' : '故障';
      let switchStatus0 = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2)
      if (switchStatus0 == '00')
        direction2MainStatus.value[0].Status6 = '无效';
      else if (switchStatus0 == '01')
        direction2MainStatus.value[0].Status6 = '强制电缆';
      else if (switchStatus0 == '10')
        direction2MainStatus.value[0].Status6 = '自动';
      else if (switchStatus0 == '11')
        direction2MainStatus.value[0].Status6 = '强制光缆';
    }

    char = getChar(13);//二方向邻站QHJ、邻站切换模式
    if (char) {
      direction2MainStatus.value[0].Status7 = getBitValueFromChar(char, 0) === '0' ? '落下(电缆)' : '吸起(光缆)';
      direction2MainStatus.value[0].Status72 = getBitValueFromChar(char, 1) === '0' ? '正常' : '故障';
      let switchStatus0 = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2)
      if (switchStatus0 == '00')
        direction2MainStatus.value[0].Status8 = '无效';
      else if (switchStatus0 == '01')
        direction2MainStatus.value[0].Status8 = '强制电缆';
      else if (switchStatus0 == '10')
        direction2MainStatus.value[0].Status8 = '自动';
      else if (switchStatus0 == '11')
        direction2MainStatus.value[0].Status8 = '强制光缆';
    }

    //判定CPU工作状态（这一步得放在某些需要知道CPU状态的操作前面）
    const workingCPU2 = ref<string>('');//记录哪个CPU（系）为主用

    char = getChar(37);
    if (char) {
      let boardStatus = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2) + getBitValueFromChar(char, 1) + getBitValueFromChar(char, 0)
      if (boardStatus == '1010') {
        boards2.value[3].status = '主用';
        workingCPU2.value = 'A'
      }
      else if (boardStatus == '0101') {
        boards2.value[3].status = '备用';
      }
      else if (boardStatus == '1001') {
        boards2.value[3].status = '故障';
      }
      else {
        boards2.value[3].status = '正常';
      }
    }

    char = getChar(46);
    if (char) {
      let boardStatus = getBitValueFromChar(char, 3) + getBitValueFromChar(char, 2) + getBitValueFromChar(char, 1) + getBitValueFromChar(char, 0)
      if (boardStatus == '1010'){
        boards2.value[4].status = '主用';
        workingCPU2.value = 'B'
      }
      else if (boardStatus == '0101'){
        boards2.value[4].status = '备用';
      }
      else if (boardStatus == '1001'){
        boards2.value[4].status = '故障';
      }
      else{
        boards2.value[4].status = '正常';
      }
    }

    const char34 = getChar(34);
    const char43 = getChar(43);
    if(char34 && char43) {
      const d2communicationStatusA = getBitValueFromChar(char34, 2)  === '0'|| getBitValueFromChar(char43, 2) === '0';
      const d2communicationStatusB = getBitValueFromChar(char34, 4)  === '0'|| getBitValueFromChar(char43, 4) === '0';
      boards2.value[1].status = (d2communicationStatusA) ? '正常' : '故障';//通信板A
      boards2.value[2].status = (d2communicationStatusB) ? '正常' : '故障';//通信板B
      direction2MainStatus.value[0].Status1 = (d2communicationStatusA) ? '正常' : '故障';
      direction2MainStatus.value[0].Status2 = (d2communicationStatusB) ? '正常' : '故障';
    }

    char = getChar(32);
    if (char) {
      direction2RelayStatusA.value[0].Status1 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction2RelayStatusA.value[0].Status2 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction2RelayStatusA.value[0].Status3 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction2RelayStatusA.value[0].Status4 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

    char = getChar(40);
    if (char) {
      direction2RelayStatusA.value[0].Status5 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction2RelayStatusA.value[0].Status6 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction2RelayStatusA.value[0].Status7 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction2RelayStatusA.value[0].Status8 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

    char = getChar(41);
    if (char) {
      direction2RelayStatusB.value[0].Status1 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction2RelayStatusB.value[0].Status2 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction2RelayStatusB.value[0].Status3 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction2RelayStatusB.value[0].Status4 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

    char = getChar(49);
    if (char) {
      direction2RelayStatusB.value[0].Status5 = getBitValueFromChar(char, 0) === '0' ? '落下' : '吸起';
      direction2RelayStatusB.value[0].Status6 = getBitValueFromChar(char, 2) === '0' ? '落下' : '吸起';
      direction2RelayStatusB.value[0].Status7 = getBitValueFromChar(char, 4) === '0' ? '落下' : '吸起';
      direction2RelayStatusB.value[0].Status8 = getBitValueFromChar(char, 6) === '0' ? '落下' : '吸起';
    }

  } catch (err) {
    console.error("Error fetching switch status:", err);
    error.value = "未获取设备状态";
    
    //无法获取设备状态时，清空所有状态
    const clearStatuses = () => {
      const statuses = [direction1MainStatus, direction1RelayStatusA, direction1RelayStatusB, direction2MainStatus, direction2RelayStatusA, direction2RelayStatusB];
      
      statuses.forEach(status => {
        status.value.forEach(item => {
          Object.keys(item).forEach(key => {
            (item as { [key: string]: string })[key] = 'null';
          });
        });
      });

      const boards = [boards1, boards2];

      boards.forEach(board => {
        board.value.forEach(item => {
          item.status = 'null';
        });
      });
    };

    clearStatuses();
  }
};

let interval: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  fetchCollapseState();
  fetchSwitchStatus();
  interval = setInterval(fetchSwitchStatus, 1000);//设置刷新数据间隔时间
});

onUnmounted(() => {
  if (interval) {
    clearInterval(interval);//清除轮询
  }
});

// 监听路由参数变化
watch(() => route.params.index, (newIndex) => {
  if (Array.isArray(newIndex)) {
    device_id.value = parseInt(newIndex[0], 10);
  } else {
    device_id.value = parseInt(newIndex, 10);
  }
  fetchCollapseState();  // 每次设备ID变化时，获取相应的折叠状态
  fetchSwitchStatus();    // 获取设备的开关状态等其他操作
});
</script>

<style scoped>
.error {
  color: red;
}

.binary-status {
            word-wrap: break-word;  /* 自动换行。旧版本浏览器 */
            word-break: break-all;  /* 现代浏览器 */
            white-space: pre-wrap;  /* 保留空白符 */
}

</style>