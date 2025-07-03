<template>
  <div>
    <h2>闭塞电压监测图</h2>
    <div>
      <label for="pageSize">最大加载点数：</label>
      <select id="pageSize" v-model="selectedPageSize">
        <option value="20">20</option>
        <option value="100">100</option>
        <option value="1000">1000</option>
        <option value="10000">10000</option>
      </select>
    </div>
    <div>
      <label for="startTime">开始时间：</label>
      <input type="datetime-local" id="startTime" v-model="startTime" />
      <label for="endTime">结束时间：</label>
      <input type="datetime-local" id="endTime" v-model="endTime" />
      <button @click="fetchData">刷新</button>
    </div>
    <div v-if="chartData.datasets.length" class="chart-container">
      <LineChart :chart-data="chartData" :options="chartOptions" />
    </div>
    <div v-else>
      <p>无数据</p>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { ref, watch, onMounted, defineComponent, type PropType, h, computed } from 'vue';
import axios from 'axios';
import { useRoute } from 'vue-router';
import { Line } from 'vue-chartjs';
import {
  Chart as ChartJS,
  Title,
  Tooltip,
  Legend,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  TimeScale,
} from 'chart.js';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';

ChartJS.register(
  Title,
  Tooltip,
  Legend,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  TimeScale,
  zoomPlugin
);

interface ChartDataPoint {
  x: string;
  y: number;
}

interface Dataset {
  label: string;
  backgroundColor: string;
  borderColor: string;
  data: ChartDataPoint[] | number[];
  hidden?: boolean;
}

interface ChartData {
  labels: string[];
  datasets: Dataset[];
}

interface RelayActionData {
  id: number;
  relay: string;
  action: string;
  timestamp: string;
  device: number;
}

interface AnalogData {
  id: number;
  voltage_1: number;
  current_1: number;
  voltage_2: number;
  current_2: number;
  timestamp: string;
  device: number;
}

const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;

const rawData = ref<{ analog: AnalogData[]; relay: RelayActionData[] }>({ analog: [], relay: [] });
const route = useRoute();
const device_id = ref<number>(parseInt(Array.isArray(route.params.index) ? route.params.index[0] : route.params.index as string, 10));
const loading = ref<boolean>(true);

const now = new Date();
const defaultStartTime = new Date(now.getTime() - 5 * 60000);

const formatDate = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
};

const formattedNow = formatDate(now);
const formatteddefaultStartTime = formatDate(defaultStartTime);

const selectedPageSize = ref<number>(1000);
const startTime = ref<string>(formatteddefaultStartTime);
const endTime = ref<string>('');

const chartOptions = ref<Record<string, any>>({
  responsive: true,
  maintainAspectRatio: false,
  scales: {
    x: {
      type: 'time',
      time: {
        unit: 'minute',
        tooltipFormat: 'MM月dd日HH:mm:ss.SSS',
        displayFormats: { minute: 'HH:mm' }
      },
      title: {
        display: true,
        text: '时间',
      },
    },
    y: {
      beginAtZero: false,
      title: {
        display: true,
        text: '数值',
      },
    },
  },
  plugins: {
    zoom: {
      pan: {
        enabled: true,
        mode: 'x',
      },
      zoom: {
        wheel: {
          enabled: true,
        },
        pinch: {
          enabled: true,
        },
        mode: 'x',
      },
    },
  },
});

const fixedOrder = [
  '一方向本站ZDJ',
  '一方向本站FDJ',
  '一方向本站ZXJ',
  '一方向本站FXJ',
  '一方向邻站ZDJ',
  '一方向邻站FDJ',
  '一方向邻站ZXJ',
  '一方向邻站FXJ',
  '二方向本站ZDJ',
  '二方向本站FDJ',
  '二方向本站ZXJ',
  '二方向本站FXJ',
  '二方向邻站ZDJ',
  '二方向邻站FDJ',
  '二方向邻站ZXJ',
  '二方向邻站FXJ',
] as const;

type FixedOrderType = typeof fixedOrder[number];

const colorMap: Record<FixedOrderType, string> = {
  '一方向本站ZDJ': 'rgba(255, 99, 132, 1)',
  '一方向本站FDJ': 'rgba(54, 162, 235, 1)',
  '一方向本站ZXJ': 'rgba(255, 206, 86, 1)',
  '一方向本站FXJ': 'rgba(75, 192, 192, 1)',
  '一方向邻站ZDJ': 'rgba(153, 102, 255, 1)',
  '一方向邻站FDJ': 'rgba(255, 159, 64, 1)',
  '一方向邻站ZXJ': 'rgba(199, 199, 199, 1)',
  '一方向邻站FXJ': 'rgba(83, 102, 255, 1)',
  '二方向本站ZDJ': 'rgba(66, 232, 122, 1)',
  '二方向本站FDJ': 'rgba(235, 52, 169, 1)',
  '二方向本站ZXJ': 'rgba(255, 105, 180, 1)',
  '二方向本站FXJ': 'rgba(0, 128, 128, 1)',
  '二方向邻站ZDJ': 'rgba(255, 215, 0, 1)',
  '二方向邻站FDJ': 'rgba(128, 0, 128, 1)',
  '二方向邻站ZXJ': 'rgba(60, 179, 113, 1)',
  '二方向邻站FXJ': 'rgba(0, 0, 255, 1)',
};

const generateAnalogDatasets = (analogData: AnalogData[]) => [
  {
    label: '一方向电压',
    backgroundColor: 'rgba(54, 162, 235, 0.2)',
    borderColor: 'rgba(54, 162, 235, 1)',
    data: analogData.map(item => ({ x: item.timestamp, y: item.voltage_1 })),
  },
  {
    label: '一方向电流',
    backgroundColor: 'rgba(255, 99, 132, 0.2)',
    borderColor: 'rgba(255, 99, 132, 1)',
    data: analogData.map(item => ({ x: item.timestamp, y: item.current_1 })),
    hidden: true,
  },
  {
    label: '二方向电压',
    backgroundColor: 'rgba(75, 192, 192, 0.2)',
    borderColor: 'rgba(75, 192, 192, 1)',
    data: analogData.map(item => ({ x: item.timestamp, y: item.voltage_2 })),
  },
  {
    label: '二方向电流',
    backgroundColor: 'rgba(153, 102, 255, 0.2)',
    borderColor: 'rgba(153, 102, 255, 1)',
    data: analogData.map(item => ({ x: item.timestamp, y: item.current_2 })),
    hidden: true,
  },
];

const generateRelayDatasets = (relayData: RelayActionData[]) => {
  const relayDatasetsMap: { [key: string]: ChartDataPoint[] } = {};

  relayData.forEach((relay) => {
    if (relay.timestamp && relay.action && relay.relay) {
      const actionValue = relay.action === '吸起' ? 100 : 0;
      if (!relayDatasetsMap[relay.relay]) {
        relayDatasetsMap[relay.relay] = [];
      }
      relayDatasetsMap[relay.relay].push({ x: relay.timestamp, y: actionValue });
    }
  });

  const relayDatasets: Dataset[] = [];
  Object.keys(relayDatasetsMap).forEach((relay) => {
    const dataPoints = relayDatasetsMap[relay];
    const newDataPoints: ChartDataPoint[] = [];

    dataPoints.forEach((point, i) => {
      newDataPoints.push(point);
      if (i < dataPoints.length - 1) {
        const nextPoint = dataPoints[i + 1];
        newDataPoints.push({ x: nextPoint.x, y: point.y });
      }
    });

    relayDatasets.push({
      label: relay as FixedOrderType,
      backgroundColor: colorMap[relay as FixedOrderType],
      borderColor: colorMap[relay as FixedOrderType],
      data: newDataPoints,
      hidden: true,
    });
  });

  relayDatasets.sort((a, b) => fixedOrder.indexOf(a.label as FixedOrderType) - fixedOrder.indexOf(b.label as FixedOrderType));
  return relayDatasets;
};

const chartData = computed<ChartData>(() => {
  const analogData = rawData.value.analog;
  const relayData = rawData.value.relay;

  const analogDatasets = generateAnalogDatasets(analogData);
  const relayDatasets = generateRelayDatasets(relayData);

  return {
    labels: analogData.map(item => item.timestamp),
    datasets: [...analogDatasets, ...relayDatasets],
  };
});

const handleError = (error: any, message: string) => {
  console.error(`${message}:`, error);
};

const fetchAnalogData = async () => {
  try {
    const params: Record<string, any> = {
      device: device_id.value,
      page_size: selectedPageSize.value,
    };
    if (startTime.value) {
      params.timestamp__gte = startTime.value;
    }
    if (endTime.value) {
      params.timestamp__lte = endTime.value;
    }
    const response = await axios.get(`${baseURL}/analog-data/`, { params });
    rawData.value.analog = response.data.results;
  } catch (error) {
    handleError(error, 'Error fetching analog data');
  }
};

const fetchRelayData = async () => {
  try {
    const params: Record<string, any> = {
      device: device_id.value,
      page_size: selectedPageSize.value,
    };
    if (startTime.value) {
      params.timestamp__gte = startTime.value;
    }
    if (endTime.value) {
      params.timestamp__lte = endTime.value;
    } else {
      const currentTime = new Date();
      const oneMinuteLater = new Date(currentTime.getTime() + 1 * 60000);
      params.timestamp__lte = oneMinuteLater.toISOString();
    }
    const response = await axios.get(`${baseURL}/relay-actions/`, { params });
    rawData.value.relay = response.data.results;
  } catch (error) {
    handleError(error, 'Error fetching relay data');
  }
};

const fetchData = async () => {
  loading.value = true;
  await Promise.all([fetchAnalogData(), fetchRelayData()]);
  loading.value = false;
};

watch(
  () => route.params.index,
  (newIndex) => {
    device_id.value = parseInt(Array.isArray(newIndex) ? newIndex[0] : newIndex as string, 10);
    fetchData();
  },
  { immediate: true }
);

onMounted(() => {
  fetchData();
});

const LineChart = defineComponent({
  name: 'LineChart',
  components: {
    Line,
  },
  props: {
    chartData: { type: Object as PropType<ChartData>, required: true },
    options: { type: Object as PropType<Record<string, any>>, required: true },
  },
  setup(props) {
    return () => h(Line, { data: props.chartData as any, options: props.options });
  },
});
</script>

<style scoped>
.chart-container {
  position: relative;
  height: 40vh;
  width: 80vw;
}
.loading-indicator {
  position: relative;
  height: 40vh;
  width: 80vw;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
