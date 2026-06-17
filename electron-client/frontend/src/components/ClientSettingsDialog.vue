<template>
  <el-dialog
    v-model="visible"
    title="服务地址设置"
    width="520px"
    :close-on-click-modal="!forceConfig"
    :close-on-press-escape="!forceConfig"
    :show-close="!forceConfig"
    @close="resetError"
  >
    <div class="client-settings-dialog">
      <el-alert
        v-if="forceConfig"
        title="首次启动需要配置前端入口地址。"
        type="warning"
        :closable="false"
        class="settings-alert"
      />
      <el-form label-width="110px" @submit.prevent>
        <el-form-item label="BT 前端入口">
          <el-input v-model="form.btBaseUrl" placeholder="http://127.0.0.1:38173" />
        </el-form-item>
        <el-form-item label="SY 前端入口">
          <el-input v-model="form.syBaseUrl" placeholder="http://127.0.0.1:38173" />
        </el-form-item>
      </el-form>
      <p class="settings-hint">
        地址填写到前端入口根路径即可，客户端会经 /bt-api、/sy-api、/bt-ws、/sy-ws 转发。
      </p>
      <p v-if="errorMessage" class="settings-error">{{ errorMessage }}</p>
    </div>

    <template #footer>
      <el-button v-if="!forceConfig" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="saveSettings">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus/es/components/message/index.mjs';
import {
  DEFAULT_CLIENT_CONFIG,
  getDesktopClientConfig,
  isDesktopClient,
  saveDesktopClientConfig,
} from '@/utils/clientRuntime';

const visible = ref(false);
const forceConfig = ref(false);
const saving = ref(false);
const errorMessage = ref('');
const form = reactive({
  btBaseUrl: DEFAULT_CLIENT_CONFIG.btBaseUrl,
  syBaseUrl: DEFAULT_CLIENT_CONFIG.syBaseUrl,
});

const resetError = () => {
  errorMessage.value = '';
};

const loadForm = () => {
  const config = getDesktopClientConfig();
  form.btBaseUrl = config?.btBaseUrl || DEFAULT_CLIENT_CONFIG.btBaseUrl;
  form.syBaseUrl = config?.syBaseUrl || DEFAULT_CLIENT_CONFIG.syBaseUrl;
  forceConfig.value = !config;
};

const openDialog = () => {
  if (!isDesktopClient()) {
    return;
  }
  loadForm();
  visible.value = true;
};

const saveSettings = async () => {
  errorMessage.value = '';
  saving.value = true;
  try {
    await saveDesktopClientConfig({
      btBaseUrl: form.btBaseUrl,
      syBaseUrl: form.syBaseUrl,
    });
    forceConfig.value = false;
    visible.value = false;
    ElMessage.success('服务地址已保存');
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '服务地址保存失败';
  } finally {
    saving.value = false;
  }
};

onMounted(() => {
  if (!isDesktopClient()) {
    return;
  }
  loadForm();
  if (forceConfig.value) {
    visible.value = true;
  }
  window.addEventListener('bt-nms-client-open-settings', openDialog);
});

onBeforeUnmount(() => {
  window.removeEventListener('bt-nms-client-open-settings', openDialog);
});
</script>

<style scoped>
.client-settings-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.settings-alert {
  margin-bottom: 4px;
}

.settings-hint {
  margin: 0;
  color: #606266;
  font-size: 13px;
  line-height: 1.5;
}

.settings-error {
  margin: 0;
  color: #f56c6c;
  font-size: 13px;
}
</style>
