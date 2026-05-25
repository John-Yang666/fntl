<template>
  <div class="ops-page">
    <section class="ops-header">
      <div>
        <h1>BT 运维管理</h1>
        <p>维护 BT 设备、车间、线路、批量导入导出和重连命令。记录页的后端入口保留为兜底入口。</p>
      </div>
      <div class="ops-header-actions">
        <el-button :loading="loading.bootstrap" @click="reloadAll">刷新</el-button>
      </div>
    </section>

    <el-alert
      v-if="pageError"
      class="ops-alert"
      type="error"
      show-icon
      :closable="false"
      :title="pageError"
    />

    <el-tabs v-model="activeTab" class="ops-tabs">
      <el-tab-pane label="设备信息" name="devices">
        <section class="ops-section">
          <div class="toolbar">
            <el-form inline class="filter-form">
              <el-form-item label="车间">
                <el-select v-model="deviceFilters.depot" clearable placeholder="全部车间" style="width: 150px">
                  <el-option v-for="depot in depots" :key="depot.id" :label="depot.name" :value="depot.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="线路">
                <el-select v-model="deviceFilters.line" clearable placeholder="全部线路" style="width: 150px">
                  <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="设备ID">
                <el-input v-model="deviceFilters.device_id" clearable style="width: 120px" />
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model="deviceFilters.name" clearable style="width: 160px" />
              </el-form-item>
              <el-form-item label="IP">
                <el-input v-model="deviceFilters.ip_address" clearable style="width: 160px" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="fetchDevices">查询</el-button>
                <el-button @click="resetDeviceFilters">重置</el-button>
              </el-form-item>
            </el-form>
            <div class="toolbar-actions">
              <el-button type="primary" @click="openDeviceDialog()">新增设备</el-button>
              <el-button @click="openImportDialog">导入设备</el-button>
              <el-button :disabled="loading.devices" @click="exportDevices">导出</el-button>
              <el-button :disabled="selectedDevices.length === 0" @click="confirmBulkReconnect">批量重连</el-button>
              <el-button type="danger" :disabled="selectedDevices.length === 0" @click="confirmBulkDelete">批量删除</el-button>
            </div>
          </div>

          <el-table
            :data="devices"
            stripe
            border
            v-loading="loading.devices"
            @selection-change="selectedDevices = $event"
          >
            <el-table-column type="selection" width="45" />
            <el-table-column prop="device_id" label="设备ID" width="90" />
            <el-table-column prop="name" label="设备名称" min-width="140" />
            <el-table-column prop="depot_name" label="车间" min-width="110" />
            <el-table-column prop="line_name" label="线路" min-width="110" />
            <el-table-column prop="ip_address" label="IP地址" min-width="140" />
            <el-table-column prop="x_coordinate" label="X" width="80" />
            <el-table-column prop="y_coordinate" label="Y" width="80" />
            <el-table-column prop="direction1_neighbor_id" label="一方向邻站" width="120" />
            <el-table-column prop="direction2_neighbor_id" label="二方向邻站" width="120" />
            <el-table-column label="方向启用" width="150">
              <template #default="{ row }">
                <el-tag :type="row.direction1_enabled ? 'success' : 'info'" size="small">一</el-tag>
                <el-tag :type="row.direction2_enabled ? 'success' : 'info'" size="small" class="tag-gap">二</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openDeviceDialog(row)">编辑</el-button>
                <el-button size="small" @click="copyDevice(row)">复制</el-button>
                <el-button size="small" @click="confirmReconnect([row])">重连</el-button>
                <el-button size="small" type="danger" @click="confirmDelete([row])">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="devicePagination.page"
              v-model:page-size="devicePagination.pageSize"
              :total="devicePagination.total"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              @current-change="fetchDevices"
              @size-change="handleDevicePageSizeChange"
            />
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="车间管理" name="depots">
        <section class="ops-section compact">
          <div class="toolbar">
            <h2>车间管理</h2>
            <el-button type="primary" @click="openDepotDialog()">新增车间</el-button>
          </div>
          <el-table :data="depots" border stripe>
            <el-table-column prop="name" label="车间名称" />
            <el-table-column prop="is_active" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="ordering" label="排序" width="100" />
            <el-table-column prop="remark" label="备注" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" @click="openDepotDialog(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="线路管理" name="lines">
        <section class="ops-section compact">
          <div class="toolbar">
            <h2>线路管理</h2>
            <el-button type="primary" @click="openLineDialog()">新增线路</el-button>
          </div>
          <el-table :data="lines" border stripe>
            <el-table-column prop="name" label="线路名称" />
            <el-table-column prop="is_active" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="ordering" label="排序" width="100" />
            <el-table-column prop="remark" label="备注" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" @click="openLineDialog(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="操作结果" name="results">
        <section class="ops-section compact">
          <el-table :data="operationResults" border stripe>
            <el-table-column prop="time" label="时间" width="180" />
            <el-table-column prop="type" label="操作" width="140" />
            <el-table-column prop="message" label="结果" />
          </el-table>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="deviceDialog.visible" :title="deviceDialog.form.id ? '编辑设备' : '新增设备'" width="760px">
      <el-form label-width="120px" :model="deviceDialog.form" class="dialog-grid">
        <el-form-item label="设备ID"><el-input-number v-model="deviceDialog.form.device_id" :min="1" /></el-form-item>
        <el-form-item label="设备名称"><el-input v-model="deviceDialog.form.name" /></el-form-item>
        <el-form-item label="车间">
          <el-select v-model="deviceDialog.form.depot_id" style="width: 100%">
            <el-option v-for="depot in depots" :key="depot.id" :label="depot.name" :value="depot.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="线路">
          <el-select v-model="deviceDialog.form.line_id" clearable style="width: 100%">
            <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="IP地址"><el-input v-model="deviceDialog.form.ip_address" /></el-form-item>
        <el-form-item label="X坐标"><el-input-number v-model="deviceDialog.form.x_coordinate" /></el-form-item>
        <el-form-item label="Y坐标"><el-input-number v-model="deviceDialog.form.y_coordinate" /></el-form-item>
        <el-form-item label="一方向邻站">
          <el-select v-model="deviceDialog.form.direction1_neighbor_id" clearable filterable style="width: 100%">
            <el-option label="无" :value="0" />
            <el-option v-for="device in devices" :key="device.id" :label="`${device.name} (${device.device_id})`" :value="device.device_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="二方向邻站">
          <el-select v-model="deviceDialog.form.direction2_neighbor_id" clearable filterable style="width: 100%">
            <el-option label="无" :value="0" />
            <el-option v-for="device in devices" :key="device.id" :label="`${device.name} (${device.device_id})`" :value="device.device_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="一方向启用"><el-switch v-model="deviceDialog.form.direction1_enabled" /></el-form-item>
        <el-form-item label="二方向启用"><el-switch v-model="deviceDialog.form.direction2_enabled" /></el-form-item>
        <el-form-item label="过滤告警码"><el-input v-model="deviceDialog.alarmFilterText" placeholder="例如 40;41" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="deviceDialog.form.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deviceDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="loading.savingDevice" @click="saveDevice">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importDialogVisible" title="导入设备" width="760px">
      <div class="import-row">
        <input ref="fileInputRef" type="file" accept=".csv,.xlsx" @change="handleImportFileChange" />
        <el-button :loading="loading.importPreview" @click="previewImport">导入预检</el-button>
      </div>
      <div class="summary-row">
        <el-tag>新增 {{ importPreview.summary.create }}</el-tag>
        <el-tag>更新 {{ importPreview.summary.update }}</el-tag>
        <el-tag :type="importPreview.summary.error ? 'danger' : 'success'">错误 {{ importPreview.summary.error }}</el-tag>
      </div>
      <el-table :data="importPreview.errors" border stripe>
        <el-table-column prop="row" label="行号" width="90" />
        <el-table-column prop="field" label="字段" width="180" />
        <el-table-column prop="message" label="错误" />
      </el-table>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="importPreview.rows.length === 0 || importPreview.summary.error > 0"
          :loading="loading.importCommit"
          @click="commitImport"
        >
          提交导入
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dictionaryDialog.visible" :title="dictionaryDialog.title" width="520px">
      <el-form label-width="80px" :model="dictionaryDialog.form">
        <el-form-item label="名称"><el-input v-model="dictionaryDialog.form.name" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="dictionaryDialog.form.is_active" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="dictionaryDialog.form.ordering" :min="0" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="dictionaryDialog.form.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dictionaryDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="loading.savingDictionary" @click="saveDictionary">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useUserStore } from '@/stores/userStore';

interface DepotLine {
  id: number;
  name: string;
  is_active: boolean;
  ordering: number;
  remark: string;
}

interface OpsDevice {
  id: string;
  device_id: number;
  name: string;
  depot_id: number;
  depot_name: string;
  line_id: number | null;
  line_name: string | null;
  ip_address: string;
  x_coordinate: number;
  y_coordinate: number;
  direction1_neighbor_id: number;
  direction1_neighbor_direction: number;
  direction2_neighbor_id: number;
  direction2_neighbor_direction: number;
  direction1_enabled: boolean;
  direction2_enabled: boolean;
  alarm_filters: number[] | string | null;
  remark: string | null;
}

interface Paginated<T> {
  count: number;
  results: T[];
}

interface ImportErrorRow {
  row: number;
  field: string;
  message: string;
}

const userStore = useUserStore();
const activeTab = ref('devices');
const pageError = ref('');
const depots = ref<DepotLine[]>([]);
const lines = ref<DepotLine[]>([]);
const devices = ref<OpsDevice[]>([]);
const selectedDevices = ref<OpsDevice[]>([]);
const importFile = ref<File | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const importDialogVisible = ref(false);
const operationResults = ref<Array<{ time: string; type: string; message: string }>>([]);

const loading = reactive({
  bootstrap: false,
  devices: false,
  savingDevice: false,
  savingDictionary: false,
  importPreview: false,
  importCommit: false,
});

const devicePagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
});

const deviceFilters = reactive({
  depot: '',
  line: '',
  device_id: '',
  name: '',
  ip_address: '',
});

const importPreview = reactive({
  summary: { create: 0, update: 0, error: 0 },
  rows: [] as Record<string, unknown>[],
  errors: [] as ImportErrorRow[],
});

const emptyDeviceForm = (): Omit<OpsDevice, 'id' | 'depot_name' | 'line_name' | 'line_id'> & { id?: string; line_id?: number } => ({
  device_id: 1,
  name: '',
  depot_id: depots.value[0]?.id ?? 0,
  line_id: lines.value[0]?.id,
  ip_address: '',
  x_coordinate: 0,
  y_coordinate: 0,
  direction1_neighbor_id: 0,
  direction1_neighbor_direction: 2,
  direction2_neighbor_id: 0,
  direction2_neighbor_direction: 1,
  direction1_enabled: true,
  direction2_enabled: true,
  alarm_filters: [],
  remark: '',
});

const deviceDialog = reactive({
  visible: false,
  alarmFilterText: '',
  form: emptyDeviceForm(),
});

const dictionaryDialog = reactive({
  visible: false,
  type: 'depot' as 'depot' | 'line',
  title: '',
  form: {
    id: undefined as number | undefined,
    name: '',
    is_active: true,
    ordering: 0,
    remark: '',
  },
});

const addResult = (type: string, message: string) => {
  operationResults.value.unshift({
    time: new Date().toLocaleString('zh-CN', { hour12: false }),
    type,
    message,
  });
};

const fetchDepots = async () => {
  const response = await userStore.requestWithAuth<Paginated<DepotLine>>('bt', {
    method: 'get',
    url: '/ops/depots/',
  });
  depots.value = response.results;
};

const fetchLines = async () => {
  const response = await userStore.requestWithAuth<Paginated<DepotLine>>('bt', {
    method: 'get',
    url: '/ops/lines/',
  });
  lines.value = response.results;
};

const buildDeviceQuery = () => {
  const params: Record<string, string | number> = {
    page: devicePagination.page,
    page_size: devicePagination.pageSize,
  };
  Object.entries(deviceFilters).forEach(([key, value]) => {
    if (value !== '') {
      params[key] = value;
    }
  });
  return params;
};

const fetchDevices = async () => {
  loading.devices = true;
  try {
    const response = await userStore.requestWithAuth<Paginated<OpsDevice>>('bt', {
      method: 'get',
      url: '/ops/devices/',
      params: buildDeviceQuery(),
    });
    devices.value = response.results;
    devicePagination.total = response.count;
  } finally {
    loading.devices = false;
  }
};

const reloadAll = async () => {
  loading.bootstrap = true;
  pageError.value = '';
  try {
    await Promise.all([fetchDepots(), fetchLines()]);
    await fetchDevices();
  } catch (error) {
    console.error(error);
    pageError.value = '运维管理数据加载失败';
  } finally {
    loading.bootstrap = false;
  }
};

const resetDeviceFilters = () => {
  Object.assign(deviceFilters, { depot: '', line: '', device_id: '', name: '', ip_address: '' });
  devicePagination.page = 1;
  void fetchDevices();
};

const handleDevicePageSizeChange = () => {
  devicePagination.page = 1;
  void fetchDevices();
};

const normalizeAlarmFilters = (value: OpsDevice['alarm_filters']) => {
  if (Array.isArray(value)) {
    return value.filter((item) => Number.isInteger(item));
  }
  if (typeof value !== 'string' || value.trim() === '') {
    return [];
  }
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed)
      ? parsed.map((item) => Number.parseInt(String(item), 10)).filter((item) => !Number.isNaN(item))
      : [];
  } catch {
    return value
      .split(/[;,，]/)
      .map((item) => Number.parseInt(item.trim(), 10))
      .filter((item) => !Number.isNaN(item));
  }
};

const openDeviceDialog = (device?: OpsDevice) => {
  const form = device ? { ...device } : emptyDeviceForm();
  const alarmFilters = normalizeAlarmFilters(form.alarm_filters);
  deviceDialog.form = {
    ...form,
    line_id: form.line_id ?? undefined,
    direction1_neighbor_id: form.direction1_neighbor_id || 0,
    direction2_neighbor_id: form.direction2_neighbor_id || 0,
    alarm_filters: alarmFilters,
    remark: form.remark ?? '',
  };
  deviceDialog.alarmFilterText = alarmFilters.join(';');
  deviceDialog.visible = true;
};

const copyDevice = (device: OpsDevice) => {
  const copied = {
    ...device,
    id: '',
    device_id: device.device_id + 1,
    name: `${device.name}-副本`,
    ip_address: '',
  };
  openDeviceDialog(copied);
};

const parseAlarmFilters = () =>
  deviceDialog.alarmFilterText
    .split(/[;,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number.parseInt(item, 10))
    .filter((item) => !Number.isNaN(item));

const saveDevice = async () => {
  loading.savingDevice = true;
  try {
    const payload = {
      ...deviceDialog.form,
      line_id: deviceDialog.form.line_id ?? null,
      alarm_filters: parseAlarmFilters(),
    };
    if (payload.id) {
      await userStore.requestWithAuth('bt', {
        method: 'patch',
        url: `/ops/devices/${payload.id}/`,
        data: payload,
      });
      addResult('设备', `已更新 ${payload.name}`);
    } else {
      await userStore.requestWithAuth('bt', {
        method: 'post',
        url: '/ops/devices/',
        data: payload,
      });
      addResult('设备', `已新增 ${payload.name}`);
    }
    deviceDialog.visible = false;
    await fetchDevices();
    ElMessage.success('设备已保存');
  } catch (error) {
    console.error(error);
    ElMessage.error('设备保存失败');
  } finally {
    loading.savingDevice = false;
  }
};

const confirmDelete = async (rows: OpsDevice[]) => {
  await ElMessageBox.confirm(
    `确定删除 ${rows.length} 台设备？该操作可能级联删除关联采集记录、告警记录、继电器动作和用户操作记录。`,
    '删除确认',
    { type: 'warning' },
  );
  if (rows.length === 1) {
    await userStore.requestWithAuth('bt', { method: 'delete', url: `/ops/devices/${rows[0].id}/` });
    addResult('删除', `已删除 ${rows[0].name}`);
  } else {
    await userStore.requestWithAuth('bt', {
      method: 'post',
      url: '/ops/devices/bulk-delete/',
      data: { device_ids: rows.map((row) => row.device_id) },
    });
    addResult('删除', `已提交批量删除 ${rows.length} 台`);
  }
  await fetchDevices();
};

const confirmBulkDelete = () => confirmDelete(selectedDevices.value);

const confirmReconnect = async (rows: OpsDevice[]) => {
  await ElMessageBox.confirm(`确定向 ${rows.length} 台设备发送重连命令？`, '重连确认', { type: 'warning' });
  const response = await userStore.requestWithAuth<{
    success: number;
    failed: number;
    skipped: number;
    results: Array<{ device_id: number; status: string; message: string }>;
  }>('bt', {
    method: 'post',
    url: '/ops/devices/reconnect/',
    data: { device_ids: rows.map((row) => row.device_id) },
  });
  addResult('重连', `成功 ${response.success}，失败 ${response.failed}，跳过 ${response.skipped}`);
  operationResults.value.unshift(
    ...response.results.map((item) => ({
      time: new Date().toLocaleString('zh-CN', { hour12: false }),
      type: `设备 ${item.device_id}`,
      message: `${item.status}: ${item.message}`,
    })),
  );
};

const confirmBulkReconnect = () => confirmReconnect(selectedDevices.value);

const getDeviceExportFilename = () => {
  const date = new Date();
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `bt-devices-${year}${month}${day}.csv`;
};

const exportDevices = async () => {
  const blob = await userStore.requestWithAuth<Blob>('bt', {
    method: 'get',
    url: '/ops/devices/export/',
    params: buildDeviceQuery(),
    responseType: 'blob',
  });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = getDeviceExportFilename();
  link.click();
  URL.revokeObjectURL(link.href);
};

const openDepotDialog = (row?: DepotLine) => openDictionaryDialog('depot', row);
const openLineDialog = (row?: DepotLine) => openDictionaryDialog('line', row);

const openDictionaryDialog = (type: 'depot' | 'line', row?: DepotLine) => {
  dictionaryDialog.type = type;
  dictionaryDialog.title = `${row ? '编辑' : '新增'}${type === 'depot' ? '车间' : '线路'}`;
  dictionaryDialog.form = row
    ? { ...row }
    : { id: undefined, name: '', is_active: true, ordering: 0, remark: '' };
  dictionaryDialog.visible = true;
};

const saveDictionary = async () => {
  loading.savingDictionary = true;
  const baseUrl = dictionaryDialog.type === 'depot' ? '/ops/depots/' : '/ops/lines/';
  try {
    if (dictionaryDialog.form.id) {
      await userStore.requestWithAuth('bt', {
        method: 'patch',
        url: `${baseUrl}${dictionaryDialog.form.id}/`,
        data: dictionaryDialog.form,
      });
    } else {
      await userStore.requestWithAuth('bt', {
        method: 'post',
        url: baseUrl,
        data: dictionaryDialog.form,
      });
    }
    dictionaryDialog.visible = false;
    await Promise.all([fetchDepots(), fetchLines()]);
    addResult(dictionaryDialog.type === 'depot' ? '车间' : '线路', `已保存 ${dictionaryDialog.form.name}`);
    ElMessage.success('保存成功');
  } catch (error) {
    console.error(error);
    ElMessage.error('保存失败');
  } finally {
    loading.savingDictionary = false;
  }
};

const resetImportPreview = () => {
  importFile.value = null;
  if (fileInputRef.value) {
    fileInputRef.value.value = '';
  }
  Object.assign(importPreview.summary, { create: 0, update: 0, error: 0 });
  importPreview.rows = [];
  importPreview.errors = [];
};

const openImportDialog = () => {
  resetImportPreview();
  importDialogVisible.value = true;
};

const handleImportFileChange = () => {
  importFile.value = fileInputRef.value?.files?.[0] ?? null;
};

const previewImport = async () => {
  if (!importFile.value) {
    ElMessage.warning('请选择导入文件');
    return;
  }
  const formData = new FormData();
  formData.append('file', importFile.value);
  loading.importPreview = true;
  try {
    const response = await userStore.requestWithAuth<{
      summary: { create: number; update: number; error: number };
      rows: Record<string, unknown>[];
      errors: ImportErrorRow[];
    }>('bt', {
      method: 'post',
      url: '/ops/devices/import/preview/',
      data: formData,
    });
    Object.assign(importPreview.summary, response.summary);
    importPreview.rows = response.rows;
    importPreview.errors = response.errors;
    addResult('导入预检', `新增 ${response.summary.create}，更新 ${response.summary.update}，错误 ${response.summary.error}`);
  } catch (error) {
    console.error(error);
    ElMessage.error('导入预检失败');
  } finally {
    loading.importPreview = false;
  }
};

const commitImport = async () => {
  loading.importCommit = true;
  try {
    const response = await userStore.requestWithAuth<{ created: number; updated: number }>('bt', {
      method: 'post',
      url: '/ops/devices/import/commit/',
      data: { rows: importPreview.rows },
    });
    addResult('导入提交', `新增 ${response.created}，更新 ${response.updated}`);
    ElMessage.success('导入完成');
    await fetchDevices();
    importDialogVisible.value = false;
    resetImportPreview();
  } finally {
    loading.importCommit = false;
  }
};

onMounted(() => {
  void reloadAll();
});
</script>

<style scoped>
.ops-page {
  padding: 20px;
  background: #f5f7fb;
  min-height: calc(100vh - 72px);
}

.ops-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.ops-header h1 {
  margin: 0 0 8px;
  font-size: 26px;
}

.ops-header p {
  margin: 0;
  color: #5f6b7a;
}

.ops-header-actions,
.toolbar-actions,
.import-row,
.summary-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.ops-alert {
  margin-bottom: 12px;
}

.ops-tabs {
  background: #fff;
  border: 1px solid #dfe5ef;
  border-radius: 8px;
  padding: 12px;
}

.ops-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.ops-section.compact {
  max-width: 1100px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.toolbar h2 {
  margin: 0;
  font-size: 18px;
}

.filter-form {
  flex: 1;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
}

.tag-gap {
  margin-left: 6px;
}

.dialog-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
}

.dialog-grid :deep(.el-form-item) {
  margin-right: 0;
}

:deep(.el-dialog) {
  max-width: calc(100vw - 32px);
}

:deep(.el-dialog__body) {
  max-height: calc(100vh - 180px);
  overflow-y: auto;
}

@media (max-width: 720px) {
  .ops-page {
    padding: 12px 8px;
  }

  .ops-tabs {
    padding: 8px;
  }

  .toolbar {
    flex-direction: column;
  }

  .toolbar-actions {
    width: 100%;
    align-items: stretch;
  }

  .toolbar-actions :deep(.el-button) {
    margin-left: 0;
  }

}
</style>
