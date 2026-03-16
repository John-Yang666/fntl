<template>
  <div ref="topologyContainer" class="topology-graph">
    <div class="topology-toolbar">
      <button @click="zoomIn">放大</button>
      <button @click="zoomOut">缩小</button>
      <button @click="fitToScreen">铺满</button>
      <div class="canvas-size-controls">
        <span class="size-label">宽</span>
        <el-input-number
          v-model="manualCanvasWidth"
          :min="MIN_CANVAS_WIDTH"
          :step="20"
          size="small"
          :disabled="autoFitCanvasWidth"
          @change="applyCanvasSize"
        />
        <span class="size-label">高</span>
        <el-input-number
          v-model="manualCanvasHeight"
          :min="MIN_CANVAS_HEIGHT"
          :step="20"
          size="small"
          @change="applyCanvasSize"
        />
        <el-checkbox v-model="autoFitCanvasWidth" @change="onAutoFitWidthChange">
          宽度自适应
        </el-checkbox>
        <button @click="applyCanvasSize">应用尺寸</button>
      </div>
    </div>
    <canvas
      ref="topologyCanvas"
      :width="canvasWidth"
      :height="canvasHeight"
      @mousedown="startDragging"
      @mousemove="onDrag"
      @mouseup="stopDragging"
      @mouseleave="stopDragging"
      @click="handleCanvasClick"
    ></canvas>
  </div>
</template>

<script lang="ts" setup>
import { onMounted, onUnmounted, ref, watch } from 'vue';
import axios from 'axios';
import { useRoute, useRouter } from 'vue-router';
import {
  reconcilePinnedDeviceKeys,
  reconcileSelectedDeviceKeys,
} from '@/utils/selectedDevices';
import {
  SYSTEMS,
  getApiBase,
  getWsBase,
  makeDeviceKey,
  type SystemType,
} from '@/utils/systems';

interface DeviceNode {
  system: SystemType;
  uniqueKey: string;
  device_id: number;
  name: string;
  ip_address: string;
  line: string;
  x_coordinate: number;
  y_coordinate: number;
  direction1_neighbor_id: number | null;
  direction2_neighbor_id: number | null;
  direction3_neighbor_id?: number | null;
  status: string;
  direction1_line_status: string;
  direction2_line_status: string;
  direction3_line_status?: string;
}

interface GroupedDevices {
  [line: string]: DeviceNode[];
}

interface TopologyStatus {
  device_id: number;
  device_status: string;
  direction1_line_status: string;
  direction2_line_status: string;
  direction3_line_status?: string;
}

const topologyContainer = ref<HTMLDivElement | null>(null);
const canvasWidth = ref(960);
const canvasHeight = ref(800);
const autoFitCanvasWidth = ref(true);
const manualCanvasWidth = ref(960);
const manualCanvasHeight = ref(800);
const groupedDevices = ref<GroupedDevices>({});
const topologyCanvas = ref<HTMLCanvasElement | null>(null);
const scale = ref(1);
const offsetX = ref(0);
const offsetY = ref(0);
const isDragging = ref(false);
const dragStartX = ref(0);
const dragStartY = ref(0);
let blinkState = true;

const route = useRoute();
const router = useRouter();
const pinnedDeviceKeys = ref<Set<string>>(new Set());

let topologySocket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let blinkInterval: ReturnType<typeof setInterval> | null = null;
let statusPollInterval: ReturnType<typeof setInterval> | null = null;
let containerResizeObserver: ResizeObserver | null = null;
const WS_RECONNECT_DELAY_MS = 3000;
const DEVICE_SETTINGS_CHANGED_EVENT = 'device-settings-changed';
const CANVAS_SIDE_GAP = 8;
const MIN_CANVAS_WIDTH = 360;
const MIN_CANVAS_HEIGHT = 300;

const normalizeCanvasSize = () => {
  if (!Number.isFinite(manualCanvasWidth.value)) {
    manualCanvasWidth.value = canvasWidth.value;
  }
  if (!Number.isFinite(manualCanvasHeight.value)) {
    manualCanvasHeight.value = canvasHeight.value;
  }

  manualCanvasWidth.value = Math.max(MIN_CANVAS_WIDTH, Math.floor(manualCanvasWidth.value));
  manualCanvasHeight.value = Math.max(MIN_CANVAS_HEIGHT, Math.floor(manualCanvasHeight.value));
};

const updateCanvasWidth = () => {
  if (!autoFitCanvasWidth.value) {
    normalizeCanvasSize();
    canvasWidth.value = manualCanvasWidth.value;
    return;
  }
  const rawContainerWidth = topologyContainer.value?.clientWidth ?? window.innerWidth;
  const containerWidth = Math.floor(rawContainerWidth - CANVAS_SIDE_GAP);
  const nextWidth = Math.max(MIN_CANVAS_WIDTH, containerWidth);
  canvasWidth.value = nextWidth;
  manualCanvasWidth.value = nextWidth;
};

const applyCanvasSize = () => {
  normalizeCanvasSize();
  canvasHeight.value = manualCanvasHeight.value;
  updateCanvasWidth();
  drawCanvas();
};

const onAutoFitWidthChange = () => {
  if (!autoFitCanvasWidth.value) {
    manualCanvasWidth.value = canvasWidth.value;
  }
  applyCanvasSize();
};

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
    const responses = await Promise.all(
      SYSTEMS.map(async (system) => ({
        system,
        data: (await axios.get(`${getApiBase(system)}/devices-list/`)).data as Record<string, Array<{
          device_id: number;
          name: string;
          ip_address: string;
          x_coordinate: number;
          y_coordinate: number;
          direction1_neighbor_id: number | null;
          direction2_neighbor_id: number | null;
          direction3_neighbor_id?: number | null;
        }>>,
      })),
    );

    const allAvailableKeys = responses.flatMap(({ system, data }) =>
      Object.values(data).flatMap((devices) =>
        devices.map((device) => makeDeviceKey(system, device.device_id)),
      ),
    );
    const selectedKeys = new Set(await reconcileSelectedDeviceKeys(allAvailableKeys));
    pinnedDeviceKeys.value = new Set(
      await reconcilePinnedDeviceKeys(Array.from(selectedKeys)),
    );

    const mergedDevices: GroupedDevices = {};
    const occupiedCoordinates = new Map<string, number>();
    responses.forEach(({ system, data }) => {
      Object.entries(data).forEach(([line, devices]) => {
        if (!mergedDevices[line]) {
          mergedDevices[line] = [];
        }

        devices.forEach((device) => {
          const deviceId = Number.parseInt(String(device.device_id), 10);
          if (Number.isNaN(deviceId)) {
            return;
          }

          const uniqueKey = makeDeviceKey(system, deviceId);
          if (selectedKeys.size > 0 && !selectedKeys.has(uniqueKey)) {
            return;
          }

          const coordinateKey = `${device.x_coordinate}:${device.y_coordinate}`;
          const collisionIndex = occupiedCoordinates.get(coordinateKey) || 0;
          occupiedCoordinates.set(coordinateKey, collisionIndex + 1);
          const coordinateOffset = collisionIndex * 28;

          mergedDevices[line].push({
            ...device,
            device_id: deviceId,
            line,
            system,
            uniqueKey,
            x_coordinate: device.x_coordinate + coordinateOffset,
            y_coordinate: device.y_coordinate + coordinateOffset,
            status: '未知状态',
            direction1_line_status: '未知状态',
            direction2_line_status: '未知状态',
            direction3_line_status: 'null',
          });
        });
      });
    });

    groupedDevices.value = mergedDevices;
    drawCanvas();
  } catch (error) {
    console.error('获取设备数据时出错！', error);
  }
};

const applyTopologyStatus = (system: SystemType, status: TopologyStatus) => {
  for (const line in groupedDevices.value) {
    const station = groupedDevices.value[line].find(
      (item) => item.system === system && item.device_id === status.device_id,
    );
    if (!station) {
      continue;
    }

    station.status = status.device_status ?? '未知状态';
    station.direction1_line_status = status.direction1_line_status ?? '未知状态';
    station.direction2_line_status = status.direction2_line_status ?? '未知状态';
    station.direction3_line_status = status.direction3_line_status ?? 'null';
    break;
  }
};

const fetchTopologyStatuses = async (system: SystemType) => {
  try {
    const response = await axios.get(`${getApiBase(system)}/all-topology-status/`);
    const statuses = response.data.topology_statuses || {};

    for (const line in groupedDevices.value) {
      groupedDevices.value[line]
        .filter((station) => station.system === system)
        .forEach((station) => {
          const status = statuses[String(station.device_id)];
          if (status && !status.error) {
            station.status = status.device_status ?? '未知状态';
            station.direction1_line_status = status.direction1_line_status ?? '未知状态';
            station.direction2_line_status = status.direction2_line_status ?? '未知状态';
            station.direction3_line_status = status.direction3_line_status ?? 'null';
          } else {
            station.status = '未知状态';
            station.direction1_line_status = '未知状态';
            station.direction2_line_status = '未知状态';
            station.direction3_line_status = 'null';
          }
        });
    }

    drawCanvas();
  } catch (error) {
    console.error(`获取 ${system.toUpperCase()} 拓扑状态失败`, error);
  }
};

const fetchAllTopologyStatuses = async () => {
  await Promise.all(SYSTEMS.map((system) => fetchTopologyStatuses(system)));
};

const clearReconnectTimer = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
};

const scheduleReconnect = () => {
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectTopologyWebSocket();
  }, WS_RECONNECT_DELAY_MS);
};

const connectTopologyWebSocket = () => {
  if (topologySocket && (topologySocket.readyState === WebSocket.OPEN || topologySocket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  clearReconnectTimer();
  topologySocket = new WebSocket(`${getWsBase('bt')}/ws/topology/`);

  topologySocket.onopen = () => {
    fetchTopologyStatuses('bt');
  };

  topologySocket.onmessage = (event: MessageEvent) => {
    try {
      const payload = JSON.parse(event.data) as TopologyStatus;
      applyTopologyStatus('bt', payload);
      drawCanvas();
    } catch (error) {
      console.error('[TopologyWS] invalid message', error);
    }
  };

  topologySocket.onerror = (error) => {
    console.error('[TopologyWS] error', error);
  };

  topologySocket.onclose = () => {
    topologySocket = null;
    scheduleReconnect();
  };
};

const disconnectTopologyWebSocket = () => {
  clearReconnectTimer();
  if (!topologySocket) {
    return;
  }
  topologySocket.onopen = null;
  topologySocket.onmessage = null;
  topologySocket.onerror = null;
  topologySocket.onclose = null;
  topologySocket.close();
  topologySocket = null;
};

const getStatusColor = (status: string) => {
  if (status === 'good') return 'lightgreen';
  if (status === 'bad') return 'red';
  if (status === 'offline') return 'lightgray';
  return 'lightgray';
};

const getLineColor = (status: string) => {
  if (status === 'good') return 'green';
  if (status === 'bad') return 'red';
  if (status === 'blink') return blinkState ? 'green' : 'red';
  return 'lightgray';
};

const getLineWidth = (status: string) => {
  if (status === 'blink') return 4;
  if (status === 'bad') return 6;
  return 2;
};

const findStationById = (system: SystemType, id: number): DeviceNode | null => {
  for (const line in groupedDevices.value) {
    const station = groupedDevices.value[line].find(
      (item) => item.system === system && item.device_id === id,
    );
    if (station) {
      return station;
    }
  }
  return null;
};

const getOrderedStations = (): DeviceNode[] => {
  const stations = Object.values(groupedDevices.value).flat();
  const pinnedStations: DeviceNode[] = [];
  const normalStations: DeviceNode[] = [];

  stations.forEach((station) => {
    if (pinnedDeviceKeys.value.has(station.uniqueKey)) {
      pinnedStations.push(station);
      return;
    }
    normalStations.push(station);
  });

  return [...normalStations, ...pinnedStations];
};

const drawCanvas = () => {
  if (!topologyCanvas.value) return;
  const ctx = topologyCanvas.value.getContext('2d');
  if (!ctx) return;

  ctx.clearRect(0, 0, topologyCanvas.value.width, topologyCanvas.value.height);
  ctx.save();
  ctx.scale(scale.value, scale.value);
  ctx.translate(offsetX.value, offsetY.value);

  const orderedStations = getOrderedStations();

  orderedStations.forEach((station) => {
    const x = station.x_coordinate;
    const y = station.y_coordinate;

    if (station.direction1_neighbor_id) {
      const previousStation = findStationById(station.system, station.direction1_neighbor_id);
      if (previousStation) {
        ctx.strokeStyle = getLineColor(station.direction1_line_status);
        ctx.lineWidth = getLineWidth(station.direction1_line_status);
        ctx.beginPath();
        ctx.moveTo(x + 50, y + 25);
        ctx.lineTo(previousStation.x_coordinate + 50, previousStation.y_coordinate + 25);
        ctx.globalAlpha = 0.5;
        ctx.stroke();
        ctx.globalAlpha = 1.0;
      }
    }

    if (station.direction2_neighbor_id) {
      const nextStation = findStationById(station.system, station.direction2_neighbor_id);
      if (nextStation) {
        ctx.strokeStyle = getLineColor(station.direction2_line_status);
        ctx.lineWidth = getLineWidth(station.direction2_line_status);
        ctx.beginPath();
        ctx.moveTo(x + 50, y + 25);
        ctx.lineTo(nextStation.x_coordinate + 50, nextStation.y_coordinate + 25);
        ctx.globalAlpha = 0.5;
        ctx.stroke();
        ctx.globalAlpha = 1.0;
      }
    }

    if (station.direction3_neighbor_id && station.direction3_line_status !== 'null') {
      const thirdStation = findStationById(station.system, station.direction3_neighbor_id);
      if (thirdStation) {
        ctx.strokeStyle = getLineColor(station.direction3_line_status || 'null');
        ctx.lineWidth = getLineWidth(station.direction3_line_status || 'null');
        ctx.beginPath();
        ctx.moveTo(x + 50, y + 25);
        ctx.lineTo(thirdStation.x_coordinate + 50, thirdStation.y_coordinate + 25);
        ctx.globalAlpha = 0.5;
        ctx.stroke();
        ctx.globalAlpha = 1.0;
      }
    }
  });

  orderedStations.forEach((station) => {
    const x = station.x_coordinate;
    const y = station.y_coordinate;

    ctx.fillStyle = getStatusColor(station.status);
    ctx.fillRect(x, y, 100, 50);
    ctx.strokeStyle = station.system === 'bt' ? '#06b6d4' : '#2563eb';
    ctx.lineWidth = pinnedDeviceKeys.value.has(station.uniqueKey) ? 3 : 2;
    ctx.strokeRect(x, y, 100, 50);

    ctx.fillStyle = 'black';
    ctx.font = '14px Arial';
    ctx.fillText(station.name, x + 10, y + 28);
  });

  ctx.restore();
};

const zoomIn = () => {
  scale.value *= 1.2;
  drawCanvas();
  saveCanvasState();
};

const zoomOut = () => {
  scale.value /= 1.2;
  drawCanvas();
  saveCanvasState();
};

const fitToScreen = () => {
  const stations = Object.values(groupedDevices.value).flat();
  if (stations.length === 0 || !topologyCanvas.value) return;

  const minX = Math.min(...stations.map((station) => station.x_coordinate));
  const maxX = Math.max(...stations.map((station) => station.x_coordinate));
  const minY = Math.min(...stations.map((station) => station.y_coordinate));
  const maxY = Math.max(...stations.map((station) => station.y_coordinate));

  const cw = topologyCanvas.value.width;
  const ch = topologyCanvas.value.height;
  const contentWidth = maxX - minX + 100;
  const contentHeight = maxY - minY + 50;

  const scaleX = cw / contentWidth;
  const scaleY = ch / contentHeight;
  scale.value = Math.min(scaleX, scaleY) * 0.9;
  offsetX.value = -minX + (cw / scale.value - contentWidth) / 2;
  offsetY.value = -minY + (ch / scale.value - contentHeight) / 2;

  drawCanvas();
  saveCanvasState();
};

const startDragging = (event: MouseEvent) => {
  isDragging.value = true;
  dragStartX.value = event.clientX;
  dragStartY.value = event.clientY;
};

const onDrag = (event: MouseEvent) => {
  if (!isDragging.value) return;
  const dx = (event.clientX - dragStartX.value) / scale.value;
  const dy = (event.clientY - dragStartY.value) / scale.value;
  offsetX.value += dx;
  offsetY.value += dy;
  dragStartX.value = event.clientX;
  dragStartY.value = event.clientY;
  drawCanvas();
};

const stopDragging = () => {
  if (isDragging.value) {
    isDragging.value = false;
    saveCanvasState();
  }
};

const handleCanvasClick = (event: MouseEvent) => {
  const x = event.offsetX / scale.value - offsetX.value;
  const y = event.offsetY / scale.value - offsetY.value;

  const orderedStations = getOrderedStations();
  for (let i = orderedStations.length - 1; i >= 0; i -= 1) {
    const station = orderedStations[i];
    if (
      x >= station.x_coordinate &&
      x <= station.x_coordinate + 100 &&
      y >= station.y_coordinate &&
      y <= station.y_coordinate + 50
    ) {
      const deviceId = Number.parseInt(String(station.device_id), 10);
      if (Number.isNaN(deviceId)) {
        return;
      }
      router.push({
        name: 'device',
        params: {
          system: station.system,
          index: String(deviceId),
        },
      });
      return;
    }
  }
};

const handleDeviceSettingsChanged = async () => {
  await fetchDevices();
  await fetchAllTopologyStatuses();
  drawCanvas();
};
const handleDeviceSettingsChangedEvent = () => {
  void handleDeviceSettingsChanged();
};

const handleResize = () => {
  updateCanvasWidth();
  drawCanvas();
};

onMounted(async () => {
  updateCanvasWidth();
  manualCanvasHeight.value = canvasHeight.value;
  await fetchDevices();
  await fetchAllTopologyStatuses();
  restoreCanvasState();
  drawCanvas();
  connectTopologyWebSocket();
  // Poll all systems as a realtime fallback when WS delivery is unstable.
  statusPollInterval = setInterval(() => {
    void fetchAllTopologyStatuses();
  }, 3000);
  blinkInterval = setInterval(() => {
    blinkState = !blinkState;
    drawCanvas();
  }, 500);
  if (topologyContainer.value) {
    containerResizeObserver = new ResizeObserver(() => {
      handleResize();
    });
    containerResizeObserver.observe(topologyContainer.value);
  }
  window.addEventListener('resize', handleResize);
  window.addEventListener(DEVICE_SETTINGS_CHANGED_EVENT, handleDeviceSettingsChangedEvent);
});

onUnmounted(() => {
  if (blinkInterval) {
    clearInterval(blinkInterval);
    blinkInterval = null;
  }
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
    statusPollInterval = null;
  }
  if (containerResizeObserver) {
    containerResizeObserver.disconnect();
    containerResizeObserver = null;
  }
  disconnectTopologyWebSocket();
  window.removeEventListener('resize', handleResize);
  window.removeEventListener(DEVICE_SETTINGS_CHANGED_EVENT, handleDeviceSettingsChangedEvent);
});

watch(
  () => route.fullPath,
  async () => {
    await fetchDevices();
    await fetchAllTopologyStatuses();
    restoreCanvasState();
  },
);
</script>

<style scoped>
.topology-graph {
  width: 100%;
  overflow-x: auto;
}

.topology-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.canvas-size-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: 12px;
}

.size-label {
  color: #606266;
  font-size: 13px;
}

:deep(.canvas-size-controls .el-input-number) {
  width: 120px;
}

canvas {
  display: block;
  box-sizing: border-box;
  border: 1px solid #ccc;
  cursor: grab;
}

canvas:active {
  cursor: grabbing;
}
</style>
