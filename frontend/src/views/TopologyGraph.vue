<template>
  <div>
    <button @click="zoomIn">放大</button>
    <button @click="zoomOut">缩小</button>
    <button @click="fitToScreen">铺满</button>
    <canvas ref="topologyCanvas" :width="canvasWidth" :height="canvasHeight" @mousedown="startDragging" @mousemove="onDrag" @mouseup="stopDragging" @mouseleave="stopDragging" @click="handleCanvasClick"></canvas>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import axios from 'axios';
import { useRoute, useRouter } from 'vue-router';
import { getFromDB } from '@/utils/indexedDB';

interface Device {
  device_id: number;
  name: string;
  ip_address: string;
  x_coordinate: number;
  y_coordinate: number;
  direction1_neighbor_id: number | null;
  direction2_neighbor_id: number | null;
  status: string;
  direction1_line_status: string;
  direction2_line_status: string;
}

interface GroupedDevices {
  [line: string]: Device[];
}

// 动态获取当前浏览器地址栏的 IP 或域名
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;

const canvasWidth = ref(window.innerWidth - 360); // 画布宽度
const canvasHeight = ref(800); // 画布高度
const groupedDevices = ref<GroupedDevices>({});
const topologyCanvas = ref<HTMLCanvasElement | null>(null);
let blinkState = true; // 闪烁状态
const scale = ref(1);
const offsetX = ref(0);
const offsetY = ref(0);
const isDragging = ref(false);
const dragStartX = ref(0);
const dragStartY = ref(0);

const route = useRoute();
const router = useRouter();

const saveCanvasState = () => {
  localStorage.setItem('canvasOffsetX', offsetX.value.toString());
  localStorage.setItem('canvasOffsetY', offsetY.value.toString());
  localStorage.setItem('canvasScale', scale.value.toString());
};

const restoreCanvasState = () => {
  const storedOffsetX = localStorage.getItem('canvasOffsetX');
  const storedOffsetY = localStorage.getItem('canvasOffsetY');
  const storedScale = localStorage.getItem('canvasScale');

  if (storedOffsetX !== null) offsetX.value = parseFloat(storedOffsetX);
  if (storedOffsetY !== null) offsetY.value = parseFloat(storedOffsetY);
  if (storedScale !== null) scale.value = parseFloat(storedScale);
};

const fetchDevices = async () => {
  try {
    const response = await axios.get(`${baseURL}/devices-list/`);
    let data: GroupedDevices = response.data;

    // 从 IndexedDB 读取并解析
    const storedSelectedDevices = await getFromDB<string>('selectedDevices');
    const selecteddevice_ids: number[] = storedSelectedDevices ? JSON.parse(storedSelectedDevices) : [];

    // 过滤设备
    const filteredGroupedDevices: GroupedDevices = {};
    for (const line in data) {
      filteredGroupedDevices[line] = data[line].filter(device =>
        selecteddevice_ids.includes(device.device_id)
      );
    }

    groupedDevices.value = filteredGroupedDevices;

    drawCanvas(); // 过滤设备后绘制画布
  } catch (error) {
    console.error('获取设备数据时出错！', error);
  }
};


const fetchAllTopologyStatuses = async () => {
  try {
    const response = await axios.get(`${baseURL}/all-topology-status/`);
    const statuses = response.data.topology_statuses;
    
    for (const line in groupedDevices.value) {
      for (const station of groupedDevices.value[line]) {
        const status = statuses[station.device_id];
        if (status) {
          station.status = status.device_status;
          station.direction1_line_status = status.direction1_line_status;
          station.direction2_line_status = status.direction2_line_status;
        } else {
          station.status = '未知状态';
          station.direction1_line_status = '未知状态';
          station.direction2_line_status = '未知状态';
        }
      }
    }
    drawCanvas();
  } catch (error) {
    console.error('There was an error fetching the topology status!', error);
  }
};

const getStatusColor = (status: string) => {
  if (status === 'good') return 'lightgreen';
  if (status === 'bad') return 'red';
  return 'lightgray'; // 未知状态
};

const getLineColor = (status: string) => {
  if (status === 'good') return 'green';
  if (status === 'bad') return 'red';
  if (status === 'blink') return blinkState ? 'green' : 'red';
  return 'lightgray'; // 未知状态
};

const getLineWidth = (status: string) => {
  if (status === 'blink') return 4; // 在闪烁状态下将线条加粗
  if (status === 'bad') return 6; // 在红色状态下将线条加粗
  return 2;
};

const drawCanvas = () => {
  if (!topologyCanvas.value) return;
  const ctx = topologyCanvas.value.getContext('2d');
  if (!ctx) return;

  // 清空画布
  ctx.clearRect(0, 0, topologyCanvas.value.width, topologyCanvas.value.height);

  ctx.save();
  ctx.scale(scale.value, scale.value);
  ctx.translate(offsetX.value, offsetY.value);

  // 绘制连接线
  for (const line in groupedDevices.value) {
    for (const station of groupedDevices.value[line]) {
      const x = station.x_coordinate;
      const y = station.y_coordinate;

      if (station.direction1_neighbor_id) {
        const previousStation = findStationById(station.direction1_neighbor_id);
        if (previousStation) {
          ctx.strokeStyle = getLineColor(station.direction1_line_status);
          ctx.lineWidth = getLineWidth(station.direction1_line_status); // 设置线条宽度
          ctx.beginPath();
          ctx.moveTo(x + 50, y + 25); // 以设备矩形的中心为起点
          ctx.lineTo(previousStation.x_coordinate + 50, previousStation.y_coordinate + 25); // 连接到上一个设备矩形的中心
          ctx.globalAlpha = 0.5; // 设置不透明度
          ctx.stroke();
          ctx.globalAlpha = 1.0; // 恢复不透明度
        }
      }
      if (station.direction2_neighbor_id) {
        const nextStation = findStationById(station.direction2_neighbor_id);
        if (nextStation) {
          ctx.strokeStyle = getLineColor(station.direction2_line_status);
          ctx.lineWidth = getLineWidth(station.direction2_line_status); // 设置线条宽度
          ctx.beginPath();
          ctx.moveTo(x + 50, y + 25); // 以设备矩形的中心为起点
          ctx.lineTo(nextStation.x_coordinate + 50, nextStation.y_coordinate + 25); // 连接到下一个设备矩形的中心
          ctx.globalAlpha = 0.5; // 设置不透明度
          ctx.stroke();
          ctx.globalAlpha = 1.0; // 恢复不透明度
        }
      }
    }
  }

  // 绘制设备矩形
  for (const line in groupedDevices.value) {
    for (const station of groupedDevices.value[line]) {
      const x = station.x_coordinate;
      const y = station.y_coordinate;

      // 绘制设备矩形
      ctx.fillStyle = getStatusColor(station.status);
      ctx.fillRect(x, y, 100, 50);

      // 绘制设备边框
      ctx.strokeStyle = 'black';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, 100, 50);

      // 绘制设备名称
      ctx.fillStyle = 'black';
      ctx.font = '15px Arial';
      const textWidth = ctx.measureText(station.name).width;
      ctx.fillText(station.name, x + (100 - textWidth) / 2, y + 30); // 名称居中显示
    }
  }

  ctx.restore();
};

const findStationById = (id: number): Device | null => {
  for (const line in groupedDevices.value) {
    const station = groupedDevices.value[line].find(station => station.device_id === id);
    if (station) {
      return station;
    }
  }
  return null;
};

const handleCanvasClick = (event: MouseEvent) => {
  const canvas = topologyCanvas.value;
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) / scale.value - offsetX.value;
  const y = (event.clientY - rect.top) / scale.value - offsetY.value;

  for (const line in groupedDevices.value) {
    for (const station of groupedDevices.value[line]) {
      const stationX = station.x_coordinate;
      const stationY = station.y_coordinate;
      if (
        x >= stationX &&
        x <= stationX + 100 &&
        y >= stationY &&
        y <= stationY + 50
      ) {
        router.push(`/device/${station.device_id}`);
        //window.location.href = `http://localhost:5173/device/${station.device_id}`;
        return;
      }
    }
  }
};

const zoomIn = () => {
  scale.value += 0.1;
  drawCanvas();
  saveCanvasState();
};

const zoomOut = () => {
  scale.value -= 0.1;
  drawCanvas();
  saveCanvasState();
};

const fitToScreen = () => {
  if (!groupedDevices.value) return;

  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const line in groupedDevices.value) {
    for (const station of groupedDevices.value[line]) {
      const x = station.x_coordinate;
      const y = station.y_coordinate;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  const canvas = topologyCanvas.value;
  if (!canvas) return;
  const canvasWidth = canvas.width;
  const canvasHeight = canvas.height;

  const contentWidth = maxX - minX + 100;
  const contentHeight = maxY - minY + 50;

  const scaleX = canvasWidth / contentWidth;
  const scaleY = canvasHeight / contentHeight;

  scale.value = Math.min(scaleX, scaleY) * 0.9; // 预留10%的边距
  offsetX.value = -minX + (canvasWidth / scale.value - contentWidth) / 2;
  offsetY.value = -minY + (canvasHeight / scale.value - contentHeight) / 2;

  drawCanvas();
  saveCanvasState();
};

const startDragging = (event: MouseEvent) => {
  isDragging.value = true;
  dragStartX.value = event.clientX;
  dragStartY.value = event.clientY;
};

const onDrag = (event: MouseEvent) => {
  if (isDragging.value) {
    const dx = (event.clientX - dragStartX.value) / scale.value;
    const dy = (event.clientY - dragStartY.value) / scale.value;
    offsetX.value += dx;
    offsetY.value += dy;
    dragStartX.value = event.clientX;
    dragStartY.value = event.clientY;
    drawCanvas();
  }
};

const stopDragging = () => {
  if (isDragging.value) {
    isDragging.value = false;
    saveCanvasState();
  }
};

let interval: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  fetchDevices().then(() => {
    fetchAllTopologyStatuses();
    restoreCanvasState();
    drawCanvas();
  });
  interval = setInterval(() => {
    fetchAllTopologyStatuses();
    blinkState = !blinkState; // 切换闪烁状态
  }, 3000); // 每3秒刷新一次状态

onUnmounted(() => {
  if (interval) {
    clearInterval(interval);//清除轮询
  }
});

  window.addEventListener('resize', () => {
    canvasWidth.value = window.innerWidth - 360; // 根据窗口大小调整画布宽度
    drawCanvas();
  });

  if (topologyCanvas.value) {
    topologyCanvas.value.addEventListener('mousedown', startDragging);
    topologyCanvas.value.addEventListener('mousemove', onDrag);
    topologyCanvas.value.addEventListener('mouseup', stopDragging);
    topologyCanvas.value.addEventListener('mouseleave', stopDragging);
    topologyCanvas.value.addEventListener('click', handleCanvasClick);
  }
});

watch(() => route.fullPath, () => {
  fetchDevices().then(() => {
    fetchAllTopologyStatuses();
    restoreCanvasState();
  });
});
</script>

<style scoped>
canvas {
  border: 1px solid black;
  cursor: grab;
}
canvas:active {
  cursor: grabbing;
}
</style>