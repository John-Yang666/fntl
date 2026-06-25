<template>
  <div class="runtime-config-page" data-testid="runtime-config-page">
    <section class="hero-card">
      <div>
        <h1>系统设置</h1>
        <p class="hero-copy">
          这里管理 BT / SY 的部分常用参数。保存后会写入后端配置中心，业务逻辑在下一次请求或下一轮后台循环中读取新值。此页面中的参数优先级高于配置文件。如果需要请谨慎修改。
        </p>
      </div>
      <div class="hero-status">
        <el-tag :type="isSuperuser ? 'success' : 'danger'" effect="dark">仅超级用户可见</el-tag>
        <span>已接入 {{ availableSystems.length }} 套系统</span>
      </div>
    </section>

    <el-alert
      v-if="availableSystems.length === 0"
      title="当前账号没有可管理的系统参数权限。"
      type="warning"
      :closable="false"
      show-icon
    />

    <el-tabs v-else v-model="activeSystem" class="system-tabs">
      <el-tab-pane
        v-for="system in availableSystems"
        :key="system"
        :name="system"
        :label="`${SYSTEM_LABELS[system]} 参数`"
        :data-testid="`runtime-tab-${system}`"
      >
        <div class="system-panel">
          <div class="system-toolbar">
            <div class="system-meta">
              <span>最近更新：{{ formatUpdatedAt(systemStates[system].payload?.updated_at) }}</span>
              <span>更新人：{{ systemStates[system].payload?.updated_by || '未记录' }}</span>
            </div>
            <div class="system-actions">
              <el-button
                :data-testid="`runtime-reload-${system}`"
                @click="reloadSystem(system)"
                :disabled="systemStates[system].loading"
              >
                重新加载
              </el-button>
              <el-button @click="resetToDefaults(system)" :disabled="!systemStates[system].payload">
                恢复默认
              </el-button>
              <el-button
                type="primary"
                :loading="systemStates[system].saving"
                :disabled="!systemStates[system].payload || systemStates[system].payload?.storage_ready === false || systemStates[system].payload?.cleanup_ready === false"
                @click="saveSystem(system)"
              >
                {{ getSaveButtonLabel(system) }}
              </el-button>
            </div>
          </div>

          <el-alert
            v-if="systemStates[system].error"
            class="panel-alert"
            type="error"
            :closable="false"
            show-icon
            :title="systemStates[system].error || ''"
          />

          <el-alert
            v-if="systemStates[system].payload?.storage_ready === false"
            class="panel-alert"
            type="warning"
            :closable="false"
            show-icon
            title="后端运行时配置表尚未迁移完成，当前展示的是默认值，暂时无法保存。"
          />

          <el-alert
            v-if="systemStates[system].payload?.cleanup_ready === false"
            class="panel-alert"
            type="warning"
            :closable="false"
            show-icon
            :title="systemStates[system].payload?.cleanup_error || '后端数据清理定时任务缺失，当前展示的是默认值，暂时无法保存。'"
          />

          <el-skeleton :loading="systemStates[system].loading" animated>
            <template #template>
              <div class="skeleton-grid">
                <el-skeleton-item variant="rect" style="height: 160px;" />
                <el-skeleton-item variant="rect" style="height: 220px;" />
              </div>
            </template>

            <template v-if="systemStates[system].payload">
              <div class="group-switcher">
                <button
                  v-for="group in getAvailableGroups(system)"
                  :key="`${system}-${group}`"
                  type="button"
                  class="group-tag"
                  :class="{ 'group-tag-active': activeGroups[system] === group }"
                  :data-testid="`runtime-${group}-group-${system}`"
                  @click="activeGroups[system] = group"
                >
                  {{ GROUP_LABELS[group] }}
                </button>
              </div>

              <section
                v-for="group in getVisibleGroups(system)"
                :key="group"
                class="group-card"
              >
                <div class="group-header">
                  <h2>{{ GROUP_LABELS[group] }}</h2>
                  <span>{{ getGroupDescription(group) }}</span>
                </div>

                <template v-if="group === 'cleanup'">
                  <div class="cleanup-toolbar">
                    <div class="cleanup-path-hint">
                      自动导出目录：<strong>DATA_DIR/cleanup_exports</strong>
                    </div>
                    <el-button
                      type="success"
                      :loading="systemStates[system].testingExport"
                      :data-testid="`runtime-cleanup-export-${system}`"
                      @click="testCleanupExport(system)"
                    >
                      导出测试
                    </el-button>
                  </div>

                  <div class="field-grid">
                    <div
                      v-if="getCleanupScheduleField(system)"
                      class="field-card"
                    >
                      <div class="field-label">{{ getRuntimeConfigFieldLabel(getCleanupScheduleField(system)?.label || '') }}</div>
                      <div class="field-input-row">
                        <el-time-picker
                          :model-value="getTimeValue(system, getCleanupScheduleField(system)?.key || '')"
                          format="HH:mm"
                          value-format="HH:mm"
                          placeholder="选择时间"
                          :clearable="false"
                          @update:model-value="updateTimeValue(system, getCleanupScheduleField(system)?.key || '', $event)"
                        />
                        <span class="field-default">默认：{{ formatDefaultValue(getCleanupScheduleField(system)?.default) }}</span>
                      </div>
                    </div>

                    <div
                      v-for="row in getCleanupRows(system)"
                      :key="row.daysField.key"
                      class="field-card cleanup-row-card"
                    >
                      <div class="field-label">{{ row.modelLabel }}</div>
                      <div class="cleanup-row-controls">
                        <div class="field-input-row cleanup-days-input">
                          <el-input-number
                            :model-value="getIntegerValue(system, row.daysField.key)"
                            :min="row.daysField.min ?? 0"
                            :max="row.daysField.max ?? undefined"
                            :step="1"
                            controls-position="right"
                            @update:model-value="updateIntegerValue(system, row.daysField.key, $event)"
                          />
                          <span class="field-unit">天</span>
                          <span class="field-default">{{ formatCleanupDaysDefault(row.daysField.default) }}</span>
                        </div>
                        <el-checkbox
                          v-if="row.autoExportField"
                          :model-value="getBooleanValue(system, row.autoExportField.key)"
                          @update:model-value="updateBooleanValue(system, row.autoExportField.key, $event)"
                        >
                          自动导出
                        </el-checkbox>
                      </div>
                    </div>
                  </div>
                </template>

                <div v-else class="field-grid">
                  <div
                    v-for="field in getFileFieldsByGroup(system, group)"
                    :key="field.key"
                    class="field-card file-field-card"
                  >
                    <div class="field-label">{{ getRuntimeConfigFieldLabel(field.label) }}</div>
                    <el-input
                      type="textarea"
                      :model-value="getFileValue(system, field.key)"
                      :autosize="{ minRows: 3, maxRows: 8 }"
                      :placeholder="field.placeholder"
                      @update:model-value="updateFileValue(system, field.key, $event)"
                    />
                    <div v-if="field.description" class="file-field-description">
                      {{ field.description }}
                    </div>
                    <div v-if="field.help_text" class="file-field-help">
                      {{ field.help_text }}
                    </div>
                  </div>

                  <div
                    v-for="field in getReadonlyFieldsByGroup(system, group)"
                    :key="field.key"
                    class="field-card readonly-field-card"
                  >
                    <div class="field-label">{{ getRuntimeConfigFieldLabel(field.label) }}</div>
                    <div class="readonly-field-value">{{ formatReadonlyFieldValue(field.value) }}</div>
                    <div v-if="field.description" class="readonly-field-description">
                      {{ field.description }}
                    </div>
                  </div>

                  <div
                    v-for="field in getFieldsByGroup(system, group)"
                    :key="field.key"
                    class="field-card"
                  >
                    <template v-if="field.type === 'integer'">
                      <div class="field-label">{{ getRuntimeConfigFieldLabel(field.label) }}</div>
                      <div class="field-input-row">
                        <el-input-number
                          :model-value="getIntegerValue(system, field.key)"
                          :min="field.min ?? 0"
                          :max="field.max ?? undefined"
                          :step="1"
                          controls-position="right"
                          @update:model-value="updateIntegerValue(system, field.key, $event)"
                        />
                        <span v-if="hasDaysUnit(getRuntimeConfigFieldLabel(field.label))" class="field-unit">天</span>
                        <span class="field-default">{{ formatRuntimeConfigDefault(getRuntimeConfigFieldLabel(field.label), field.default) }}</span>
                      </div>
                    </template>

                    <template v-else-if="field.type === 'time'">
                      <div class="field-label">{{ getRuntimeConfigFieldLabel(field.label) }}</div>
                      <div class="field-input-row">
                        <el-time-picker
                          :model-value="getTimeValue(system, field.key)"
                          format="HH:mm"
                          value-format="HH:mm"
                          placeholder="选择时间"
                          :clearable="false"
                          @update:model-value="updateTimeValue(system, field.key, $event)"
                        />
                        <span class="field-default">默认：{{ formatDefaultValue(field.default) }}</span>
                      </div>
                    </template>

                    <template v-else-if="field.type === 'boolean'">
                      <div class="field-label">{{ getRuntimeConfigFieldLabel(field.label) }}</div>
                      <el-checkbox
                        :model-value="getBooleanValue(system, field.key)"
                        @update:model-value="updateBooleanValue(system, field.key, $event)"
                      >
                        启用
                      </el-checkbox>
                    </template>

                    <template v-else>
                      <div class="field-label">{{ getRuntimeConfigFieldLabel(field.label) }}</div>
                      <div class="delay-table-wrap">
                        <el-table :data="getAlarmDelayRows(system, field)" border stripe>
                          <el-table-column prop="code" label="告警码" width="100" />
                          <el-table-column prop="meaning" label="告警含义" min-width="220" />
                          <el-table-column label="延时秒数" width="180">
                            <template #default="{ row }">
                              <el-input-number
                                :model-value="row.delay"
                                :min="field.min ?? 0"
                                :max="field.max ?? undefined"
                                :step="1"
                                controls-position="right"
                                @update:model-value="updateAlarmDelayValue(system, field.key, row.code, $event)"
                              />
                            </template>
                          </el-table-column>
                        </el-table>
                      </div>
                    </template>
                  </div>
                </div>
              </section>
            </template>
          </el-skeleton>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="savePasswordDialog.visible"
      title="验证登录密码"
      width="420px"
      :close-on-click-modal="false"
      :before-close="handleSavePasswordDialogClose"
    >
      <div class="save-password-dialog-copy">
        请输入当前登录用户
        <strong>{{ savePasswordDialogUsername || '未知用户' }}</strong>
        的登录密码，以保存
        <strong>{{ savePasswordDialogSystemLabel || '当前' }}</strong>
        系统设置。
      </div>
      <el-input
        v-model="savePasswordDialog.password"
        type="password"
        show-password
        placeholder="请输入登录密码"
        @keydown.enter.prevent="confirmSaveWithPassword"
      />
      <div v-if="savePasswordDialog.error" class="save-password-dialog-error">
        {{ savePasswordDialog.error }}
      </div>
      <template #footer>
        <div class="save-password-dialog-actions">
          <el-button @click="closeSavePasswordDialog">取消</el-button>
          <el-button
            type="primary"
            :loading="savePasswordDialog.verifying"
            @click="confirmSaveWithPassword"
          >
            确认
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import axios from 'axios';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus/es/components/message/index.mjs';
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs';
import { useUserStore } from '@/stores/userStore';
import {
  formatCleanupDaysDefault,
  formatRuntimeConfigDefault,
  getCleanupModelLabel,
  getRuntimeConfigFieldLabel,
  hasDaysUnit,
  translateRuntimeConfigText,
} from '@/utils/runtimeConfigLabels';
import { SYSTEMS, SYSTEM_LABELS, getApiBase, type SystemType } from '@/utils/systems';

type RuntimeConfigGroup = 'runtime' | 'auth' | 'cleanup' | 'security';
type RuntimeConfigFieldType = 'integer' | 'alarm_delay_map' | 'time' | 'boolean';

interface RuntimeConfigField {
  key: string;
  label: string;
  type: RuntimeConfigFieldType;
  group: RuntimeConfigGroup;
  min?: number | null;
  max?: number | null;
  default: unknown;
  codes?: number[];
  alarm_meanings?: Record<string, string>;
}

interface RuntimeConfigReadonlyField {
  key: string;
  label: string;
  type: 'text';
  group: RuntimeConfigGroup;
  value: unknown;
  description?: string;
}

interface RuntimeConfigFileField {
  key: string;
  label: string;
  type: 'textarea';
  group: RuntimeConfigGroup;
  description?: string;
  help_text?: string;
  placeholder?: string;
}

interface RuntimeConfigPayload {
  schema: RuntimeConfigField[];
  file_fields?: RuntimeConfigFileField[];
  file_values?: Record<string, string>;
  file_save_errors?: Record<string, string>;
  readonly_fields?: RuntimeConfigReadonlyField[];
  defaults: Record<string, unknown>;
  values: Record<string, unknown>;
  updated_at: string | null;
  updated_by: string | null;
  storage_ready?: boolean;
  cleanup_ready?: boolean;
  cleanup_error?: string | null;
}

interface RuntimeConfigState {
  loading: boolean;
  saving: boolean;
  testingExport: boolean;
  error: string | null;
  payload: RuntimeConfigPayload | null;
  draftValues: Record<string, unknown>;
  draftFileValues: Record<string, string>;
}

interface AlarmDelayRow {
  code: number;
  meaning: string;
  delay: number;
}

interface SavePasswordDialogState {
  visible: boolean;
  system: SystemType | null;
  password: string;
  error: string;
  verifying: boolean;
}

interface CleanupRow {
  modelLabel: string;
  daysField: RuntimeConfigField;
  autoExportField?: RuntimeConfigField;
}

interface CleanupExportTestResult {
  status: string;
  model: string;
  candidate_count: number;
  export_path: string;
  error: string;
}

interface CleanupExportTestPayload {
  results: Record<string, CleanupExportTestResult>;
}

const GROUP_ORDER: RuntimeConfigGroup[] = ['runtime', 'cleanup', 'auth', 'security'];
const GROUP_LABELS: Record<RuntimeConfigGroup, string> = {
  runtime: '运行参数',
  cleanup: '数据清理',
  auth: '认证参数',
  security: '安全参数',
};
const DEPLOY_HOST_IP_FILE_KEY = 'DEPLOY_HOST_IPS';
const DEPLOY_HOST_IP_HELP_TEXT = '支持写一个或多个，多个可用逗号、分号或换行分隔';
const DEPLOY_HOST_IP_NORMALIZED_HELP_TEXT = DEPLOY_HOST_IP_HELP_TEXT
  .replace(/[，、]/g, ',')
  .replace(/；/g, ';')
  .replace(/[。．｡]/g, '.')
  .replace(/：/g, ':')
  .replace(/　/g, ' ');
const DEPLOY_HOST_IP_LEGACY_HINT_LINES = new Set([
  DEPLOY_HOST_IP_HELP_TEXT,
  `# ${DEPLOY_HOST_IP_HELP_TEXT}`,
  DEPLOY_HOST_IP_NORMALIZED_HELP_TEXT,
  `# ${DEPLOY_HOST_IP_NORMALIZED_HELP_TEXT}`,
]);
const ACTIVE_SYSTEM_STORAGE_KEY = 'runtime-config-active-system';

const userStore = useUserStore();
const isSuperuser = computed(() => userStore.isSuperuser);

const systemStates = reactive<Record<SystemType, RuntimeConfigState>>({
  bt: {
    loading: false,
    saving: false,
    testingExport: false,
    error: null,
    payload: null,
    draftValues: {},
    draftFileValues: {},
  },
  sy: {
    loading: false,
    saving: false,
    testingExport: false,
    error: null,
    payload: null,
    draftValues: {},
    draftFileValues: {},
  },
});
const activeGroups = reactive<Record<SystemType, RuntimeConfigGroup>>({
  bt: 'runtime',
  sy: 'runtime',
});

const availableSystems = computed<SystemType[]>(() =>
  SYSTEMS.filter((system) => userStore.isSystemSuperuser(system)),
);

function getStoredActiveSystem(): SystemType | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const storedValue = window.localStorage.getItem(ACTIVE_SYSTEM_STORAGE_KEY);
  return storedValue === 'bt' || storedValue === 'sy' ? storedValue : null;
}

const activeSystem = ref<SystemType>(getStoredActiveSystem() || 'bt');
const savePasswordDialog = reactive<SavePasswordDialogState>({
  visible: false,
  system: null,
  password: '',
  error: '',
  verifying: false,
});
const savePasswordDialogSystemLabel = computed(() =>
  savePasswordDialog.system ? SYSTEM_LABELS[savePasswordDialog.system] : '',
);
const savePasswordDialogUsername = computed(() =>
  savePasswordDialog.system ? userStore.getUser(savePasswordDialog.system)?.username ?? '' : '',
);

watch(
  availableSystems,
  (systems) => {
    if (systems.length > 0 && !systems.includes(activeSystem.value)) {
      activeSystem.value = systems[0];
    }
  },
  { immediate: true },
);

watch(activeSystem, (system) => {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(ACTIVE_SYSTEM_STORAGE_KEY, system);
});

function cloneValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
  }
  return fallback;
}

function getFileSaveErrorMessages(errors: Record<string, string> | undefined): string[] {
  return Object.values(errors || {}).filter((message) => message.trim().length > 0);
}

function getFieldsByGroup(system: SystemType, group: RuntimeConfigGroup): RuntimeConfigField[] {
  return (systemStates[system].payload?.schema || []).filter((field) => field.group === group);
}

function getFileFieldsByGroup(system: SystemType, group: RuntimeConfigGroup): RuntimeConfigFileField[] {
  return (systemStates[system].payload?.file_fields || []).filter((field) => field.group === group);
}

function getReadonlyFieldsByGroup(system: SystemType, group: RuntimeConfigGroup): RuntimeConfigReadonlyField[] {
  return (systemStates[system].payload?.readonly_fields || []).filter((field) => field.group === group);
}

function getAvailableGroups(system: SystemType): RuntimeConfigGroup[] {
  const schema = systemStates[system].payload?.schema || [];
  const fileFields = systemStates[system].payload?.file_fields || [];
  const readonlyFields = systemStates[system].payload?.readonly_fields || [];
  return GROUP_ORDER.filter(
    (group) =>
      schema.some((field) => field.group === group) ||
      fileFields.some((field) => field.group === group) ||
      readonlyFields.some((field) => field.group === group),
  );
}

function getVisibleGroups(system: SystemType): RuntimeConfigGroup[] {
  const groups = getAvailableGroups(system);
  const activeGroup = activeGroups[system];
  if (groups.length === 0) {
    return [];
  }
  if (!groups.includes(activeGroup)) {
    activeGroups[system] = groups[0];
    return [groups[0]];
  }
  return [activeGroup];
}

function getIntegerValue(system: SystemType, key: string): number {
  const rawValue = systemStates[system].draftValues[key];
  return typeof rawValue === 'number' ? rawValue : Number(rawValue || 0);
}

function getTimeValue(system: SystemType, key: string): string {
  const rawValue = systemStates[system].draftValues[key];
  return typeof rawValue === 'string' ? rawValue : '';
}

function getBooleanValue(system: SystemType, key: string): boolean {
  return systemStates[system].draftValues[key] === true;
}

function getFileValue(system: SystemType, key: string): string {
  return systemStates[system].draftFileValues[key] ?? '';
}

function normalizeDeployHostFileContent(value: string): string {
  const normalized = value
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/[，、]/g, ',')
    .replace(/；/g, ';')
    .replace(/[。．｡]/g, '.')
    .replace(/：/g, ':')
    .replace(/　/g, ' ');

  return normalized
    .split('\n')
    .filter((line) => !DEPLOY_HOST_IP_LEGACY_HINT_LINES.has(line.trim()))
    .map((line) => line.replace(/\s+$/g, ''))
    .join('\n');
}

function getDeployHostEntries(value: string): string[] {
  return value
    .split('\n')
    .flatMap((line) => line.split('#', 1)[0].split(/[,;\s]+/))
    .map((item) => item.trim())
    .filter(Boolean);
}

function isValidIpv4Address(value: string): boolean {
  const parts = value.split('.');
  if (parts.length !== 4) {
    return false;
  }
  return parts.every((part) => {
    if (!/^\d+$/.test(part)) {
      return false;
    }
    const parsed = Number(part);
    return parsed >= 0 && parsed <= 255 && String(parsed) === part.replace(/^0+(?=\d)/, '');
  });
}

function isLikelyIpv6Address(value: string): boolean {
  return /^[0-9a-fA-F:]+$/.test(value) && value.includes(':');
}

function validateDeployHostFileContent(value: string): string | null {
  const invalidEntries = getDeployHostEntries(normalizeDeployHostFileContent(value)).filter(
    (entry) => !isValidIpv4Address(entry) && !isLikelyIpv6Address(entry),
  );
  if (invalidEntries.length > 0) {
    return `网管IP格式不正确：${invalidEntries.join(', ')}。${DEPLOY_HOST_IP_HELP_TEXT}。`;
  }
  return null;
}

function updateIntegerValue(system: SystemType, key: string, value: number | undefined): void {
  systemStates[system].draftValues[key] = typeof value === 'number' ? value : 0;
}

function updateTimeValue(system: SystemType, key: string, value: string | null): void {
  systemStates[system].draftValues[key] = typeof value === 'string' ? value : '';
}

function updateBooleanValue(system: SystemType, key: string, value: string | number | boolean): void {
  systemStates[system].draftValues[key] = value === true;
}

function updateFileValue(system: SystemType, key: string, value: string): void {
  systemStates[system].draftFileValues[key] = key === DEPLOY_HOST_IP_FILE_KEY
    ? normalizeDeployHostFileContent(value)
    : value;
}

function getCleanupScheduleField(system: SystemType): RuntimeConfigField | undefined {
  return getFieldsByGroup(system, 'cleanup').find((field) => field.key === 'CLEANUP_SCHEDULE_TIME');
}

function getCleanupRows(system: SystemType): CleanupRow[] {
  const fields = getFieldsByGroup(system, 'cleanup');
  const fieldMap = new Map(fields.map((field) => [field.key, field]));
  return fields
    .filter((field) => field.type === 'integer' && field.key.endsWith('_DAYS'))
    .map((daysField) => {
      const autoExportKey = daysField.key.replace(/_DAYS$/, '_AUTO_EXPORT');
      return {
        modelLabel: getCleanupModelLabel(daysField.label),
        daysField,
        autoExportField: fieldMap.get(autoExportKey),
      };
    });
}

function getAlarmDelayRows(system: SystemType, field: RuntimeConfigField): AlarmDelayRow[] {
  const rawMap = systemStates[system].draftValues[field.key];
  const delayMap = (rawMap && typeof rawMap === 'object' ? rawMap : {}) as Record<string, unknown>;
  return (field.codes || []).map((code) => ({
    code,
    meaning: field.alarm_meanings?.[String(code)] || '未命名告警',
    delay: Number(delayMap[String(code)] ?? 0),
  }));
}

function updateAlarmDelayValue(
  system: SystemType,
  key: string,
  code: number,
  value: number | undefined,
): void {
  const currentMap = cloneValue(
    (systemStates[system].draftValues[key] && typeof systemStates[system].draftValues[key] === 'object')
      ? systemStates[system].draftValues[key]
      : {},
  ) as Record<string, unknown>;
  currentMap[String(code)] = typeof value === 'number' ? value : 0;
  systemStates[system].draftValues[key] = currentMap;
}

function formatUpdatedAt(value: string | null | undefined): string {
  if (!value) {
    return '未修改';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatDefaultValue(value: unknown): string {
  if (typeof value === 'number') {
    return String(value);
  }
  if (typeof value === 'string') {
    return value;
  }
  return '-';
}

function formatReadonlyFieldValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join(', ') : '未配置';
  }
  if (typeof value === 'string') {
    return value.trim() || '未配置';
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '未配置';
}

function getGroupDescription(group: RuntimeConfigGroup): string {
  if (group === 'runtime') {
    return '业务运行参数';
  }
  if (group === 'cleanup') {
    return '数据保留与定时清理任务';
  }
  if (group === 'security') {
    return '当前后端允许访问的主机与跨域来源';
  }
  return translateRuntimeConfigText('Token 有效期参数');
}

function resetToDefaults(system: SystemType): void {
  const payload = systemStates[system].payload;
  if (!payload) {
    return;
  }
  systemStates[system].draftValues = cloneValue(payload.defaults);
  systemStates[system].draftFileValues = cloneValue(payload.file_values || {});
}

function validateDraft(system: SystemType): string | null {
  const payload = systemStates[system].payload;
  if (!payload) {
    return '配置尚未加载完成。';
  }

  for (const field of payload.schema) {
    const rawValue = systemStates[system].draftValues[field.key];
    if (field.type === 'integer') {
      if (typeof rawValue !== 'number' || Number.isNaN(rawValue)) {
        return `${getRuntimeConfigFieldLabel(field.label)} 不能为空。`;
      }
    }
    if (field.type === 'time') {
      if (typeof rawValue !== 'string' || !/^\d{2}:\d{2}$/.test(rawValue)) {
        return `${getRuntimeConfigFieldLabel(field.label)} 必须是 HH:mm 格式。`;
      }
      const [hour, minute] = rawValue.split(':').map((item) => Number(item));
      if (hour > 23 || minute > 59) {
        return `${getRuntimeConfigFieldLabel(field.label)} 必须是合法时间。`;
      }
    }
    if (field.type === 'boolean') {
      if (typeof rawValue !== 'boolean') {
        return `${getRuntimeConfigFieldLabel(field.label)} 必须是布尔值。`;
      }
    }
    if (field.type === 'alarm_delay_map') {
      if (!rawValue || typeof rawValue !== 'object') {
        return `${getRuntimeConfigFieldLabel(field.label)} 不能为空。`;
      }
      const currentMap = rawValue as Record<string, unknown>;
      const missingCodes = (field.codes || []).filter((code) => currentMap[String(code)] === undefined);
      if (missingCodes.length > 0) {
        return `${getRuntimeConfigFieldLabel(field.label)} 缺少告警码：${missingCodes.join(', ')}`;
      }
    }
  }

  const deployHostFileContent = systemStates[system].draftFileValues[DEPLOY_HOST_IP_FILE_KEY];
  if (typeof deployHostFileContent === 'string') {
    const deployHostValidationError = validateDeployHostFileContent(deployHostFileContent);
    if (deployHostValidationError) {
      return deployHostValidationError;
    }
  }

  return null;
}

async function testCleanupExport(system: SystemType): Promise<void> {
  const state = systemStates[system];
  state.testingExport = true;
  state.error = null;
  try {
    const payload = await userStore.requestWithAuth<CleanupExportTestPayload>(system, {
      method: 'post',
      url: '/runtime-config/cleanup-export-test/',
    });
    const lines = Object.entries(payload.results).map(([name, result]) => {
      const modelName = translateRuntimeConfigText(name);
      if (result.status === 'failed') {
        return `${modelName}：失败，${result.error || '未知错误'}`;
      }
      return `${modelName}：成功，候选 ${result.candidate_count} 条，文件 ${result.export_path || '-'}`;
    });
    await ElMessageBox.alert(lines.join('\n'), `${SYSTEM_LABELS[system]} 导出测试结果`, {
      confirmButtonText: '确定',
      customClass: 'cleanup-export-test-dialog',
    });
    ElMessage.success(`${SYSTEM_LABELS[system]} 导出测试完成`);
  } catch (error) {
    state.error = getErrorMessage(error, `${SYSTEM_LABELS[system]} 导出测试失败`);
    ElMessage.error(state.error);
  } finally {
    state.testingExport = false;
  }
}

function hasUnsavedChanges(system: SystemType): boolean {
  const payload = systemStates[system].payload;
  if (!payload) {
    return false;
  }

  return (
    JSON.stringify(systemStates[system].draftValues) !== JSON.stringify(payload.values) ||
    JSON.stringify(systemStates[system].draftFileValues) !== JSON.stringify(payload.file_values || {})
  );
}

function getSaveButtonLabel(system: SystemType): string {
  return `${hasUnsavedChanges(system) ? '* ' : ''}保存参数`;
}

function resetSavePasswordDialog(): void {
  savePasswordDialog.visible = false;
  savePasswordDialog.system = null;
  savePasswordDialog.password = '';
  savePasswordDialog.error = '';
  savePasswordDialog.verifying = false;
}

function closeSavePasswordDialog(): void {
  resetSavePasswordDialog();
}

function handleSavePasswordDialogClose(done: () => void): void {
  resetSavePasswordDialog();
  done();
}

function openSavePasswordDialog(system: SystemType): void {
  savePasswordDialog.visible = true;
  savePasswordDialog.system = system;
  savePasswordDialog.password = '';
  savePasswordDialog.error = '';
  savePasswordDialog.verifying = false;
}

async function verifySavePassword(system: SystemType, password: string): Promise<void> {
  const username = userStore.getUser(system)?.username;
  if (!username) {
    throw new Error(`当前 ${SYSTEM_LABELS[system]} 用户信息缺失，请重新登录后再保存。`);
  }

  await axios.post(`${getApiBase(system)}/token/`, {
    username,
    password,
  });
}

async function loadSystem(system: SystemType): Promise<void> {
  const state = systemStates[system];
  state.loading = true;
  state.error = null;
  try {
    const payload = await userStore.requestWithAuth<RuntimeConfigPayload>(system, {
      method: 'get',
      url: '/runtime-config/',
      params: {
        _ts: Date.now(),
      },
    });
    state.payload = payload;
    state.draftValues = cloneValue(payload.values);
    state.draftFileValues = cloneValue(payload.file_values || {});
    const availableGroups = getAvailableGroups(system);
    if (availableGroups.length > 0 && !availableGroups.includes(activeGroups[system])) {
      activeGroups[system] = availableGroups[0];
    }
  } catch (error) {
    state.error = getErrorMessage(error, `${SYSTEM_LABELS[system]} 参数加载失败`);
  } finally {
    state.loading = false;
  }
}

async function reloadSystem(system: SystemType): Promise<void> {
  await loadSystem(system);
  if (!systemStates[system].error) {
    ElMessage.success(`${SYSTEM_LABELS[system]} 参数已刷新`);
  }
}

async function saveSystem(system: SystemType): Promise<void> {
  if (!hasUnsavedChanges(system)) {
    ElMessage.info('当前没有未保存的修改');
    return;
  }

  openSavePasswordDialog(system);
}

async function confirmSaveWithPassword(): Promise<void> {
  const system = savePasswordDialog.system;
  if (!system) {
    return;
  }

  const validationError = validateDraft(system);
  if (validationError) {
    ElMessage.warning(validationError);
    return;
  }

  if (!savePasswordDialog.password) {
    savePasswordDialog.error = '请输入登录密码。';
    return;
  }

  const state = systemStates[system];
  savePasswordDialog.verifying = true;
  savePasswordDialog.error = '';
  state.saving = true;
  state.error = null;
  try {
    await verifySavePassword(system, savePasswordDialog.password);
    const payload = await userStore.requestWithAuth<RuntimeConfigPayload>(system, {
      method: 'put',
      url: '/runtime-config/',
      data: {
        values: cloneValue(state.draftValues),
        file_values: cloneValue(state.draftFileValues),
      },
    });
    state.payload = payload;
    state.draftValues = cloneValue(payload.values);
    state.draftFileValues = cloneValue(payload.file_values || {});
    resetSavePasswordDialog();
    const fileSaveErrorMessages = getFileSaveErrorMessages(payload.file_save_errors);
    if (fileSaveErrorMessages.length > 0) {
      ElMessage.warning(`${SYSTEM_LABELS[system]} 参数已保存，但${fileSaveErrorMessages.join('；')}`);
    } else {
      ElMessage.success(`${SYSTEM_LABELS[system]} 参数已保存`);
    }
  } catch (error) {
    if (axios.isAxiosError(error) && error.config?.url?.includes('/token/')) {
      savePasswordDialog.error = '登录密码验证失败，请重试。';
      return;
    }
    state.error = getErrorMessage(error, `${SYSTEM_LABELS[system]} 参数保存失败`);
    savePasswordDialog.error = state.error;
    ElMessage.error(state.error);
  } finally {
    savePasswordDialog.verifying = false;
    state.saving = false;
  }
}

onMounted(async () => {
  await Promise.all(availableSystems.value.map((system) => loadSystem(system)));
});
</script>

<style scoped>
.runtime-config-page {
  min-height: calc(100vh - 92px);
  padding: 28px;
  background: #ffffff;
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 30px;
  margin-bottom: 18px;
  border: 1px solid rgba(127, 29, 29, 0.08);
  border-radius: 24px;
  background: linear-gradient(180deg, #ffffff 0%, #f5f7fb 100%);
}

.hero-card h1 {
  margin: 0;
  color: #1f2937;
  font-size: 32px;
}

.hero-copy {
  max-width: 760px;
  margin: 10px 0 0;
  color: #4b5563;
  line-height: 1.7;
}

.hero-status {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
  color: #6b7280;
  font-size: 14px;
  white-space: nowrap;
}

.system-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
  background: #ffffff;
}

.system-tabs :deep(.el-tabs__nav-wrap),
.system-tabs :deep(.el-tabs__nav-scroll),
.system-tabs :deep(.el-tabs__content),
.system-tabs :deep(.el-tab-pane) {
  background: #ffffff;
}

.system-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
  background: #ffffff;
}

.cleanup-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 16px;
  background: #f8fafc;
}

.cleanup-path-hint {
  color: #64748b;
  font-size: 14px;
}

.cleanup-path-hint strong {
  color: #1f2937;
  font-weight: 700;
}

.cleanup-row-card {
  min-height: 154px;
}

.cleanup-row-controls {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.cleanup-days-input {
  align-items: center;
}

.system-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-radius: 18px;
  background: #ffffff;
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.system-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  color: #475569;
  font-size: 14px;
}

.system-actions {
  display: flex;
  gap: 28px;
  align-items: center;
  flex-wrap: wrap;
}

.panel-alert {
  margin-bottom: 4px;
}

.skeleton-grid {
  display: grid;
  gap: 18px;
}

.group-switcher {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.group-tag {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 999px;
  background: #ffffff;
  color: #475569;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.group-tag:hover {
  border-color: rgba(59, 130, 246, 0.4);
  color: #2563eb;
}

.group-tag-active {
  background: #eff6ff;
  border-color: rgba(37, 99, 235, 0.35);
  color: #2563eb;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12);
}

.group-card {
  padding: 20px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 20px;
  background: #ffffff;
  box-shadow: 0 14px 40px rgba(148, 163, 184, 0.08);
}

.group-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.group-header h2 {
  margin: 0;
  color: #111827;
  font-size: 20px;
}

.group-header span {
  color: #6b7280;
  font-size: 13px;
}

.field-grid {
  display: grid;
  gap: 18px;
}

.field-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.readonly-field-card {
  border-color: rgba(59, 130, 246, 0.28);
  background: #f8fbff;
}

.file-field-card {
  border-color: rgba(37, 99, 235, 0.32);
  background: #f8fbff;
}

.field-label {
  color: #1f2937;
  font-size: 15px;
  font-weight: 600;
}

.readonly-field-value {
  min-height: 32px;
  color: #334155;
  font-size: 15px;
  font-weight: 600;
  line-height: 32px;
  word-break: break-word;
}

.readonly-field-description {
  color: #64748b;
  font-size: 13px;
  line-height: 20px;
  word-break: break-word;
}

.file-field-description {
  color: #64748b;
  font-size: 13px;
  line-height: 20px;
  word-break: break-word;
}

.file-field-help {
  color: #2563eb;
  font-size: 13px;
  line-height: 20px;
  word-break: break-word;
}

.field-input-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.field-default {
  color: #9ca3af;
  font-size: 13px;
}

.field-unit {
  color: #475569;
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
}

.save-password-dialog-copy {
  margin-bottom: 16px;
  color: #475569;
  line-height: 1.7;
}

.save-password-dialog-error {
  margin-top: 10px;
  color: #dc2626;
  font-size: 13px;
}

.save-password-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.delay-table-wrap {
  overflow: hidden;
  border-radius: 14px;
}

@media (max-width: 900px) {
  .runtime-config-page {
    padding: 16px;
  }

  .hero-card,
  .system-toolbar,
  .group-header {
    flex-direction: column;
  }

  .hero-status {
    align-items: flex-start;
  }

  .system-actions {
    flex-wrap: wrap;
  }

  .field-input-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
