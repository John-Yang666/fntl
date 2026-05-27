<template>
  <el-card>
    <template #header>文件管理</template>

    <el-tabs v-model="activeSystem">
      <el-tab-pane label="BT 文件" name="bt" />
      <el-tab-pane label="SY 文件" name="sy" />
    </el-tabs>

    <el-form v-if="isAdmin" :inline="true" style="margin-bottom: 20px">
      <el-form-item label="备注名称">
        <el-input v-model="remark" placeholder="请输入备注" style="width: 300px" />
      </el-form-item>
      <el-form-item>
        <el-upload
          :http-request="customUpload"
          :show-file-list="false"
          :before-upload="beforeUpload"
          accept=""
        >
          <el-button type="primary">选择文件并上传</el-button>
        </el-upload>
      </el-form-item>
    </el-form>

    <el-divider>已上传文件</el-divider>

    <el-table :data="currentFiles" style="width: 100%">
      <el-table-column prop="name" label="备注名称" />
      <el-table-column prop="upload_time" label="上传时间" />
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button type="success" size="small" @click="downloadFile(row)">下载</el-button>
          <el-popconfirm
            v-if="isAdmin"
            title="确认删除该文件？"
            @confirm="deleteFile(row.id)"
          >
            <template #reference>
              <el-button type="danger" size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/userStore';
import { SYSTEMS, type SystemType } from '@/utils/systems';

interface UploadedFile {
  id: number;
  name: string;
  upload_time: string;
}

const userStore = useUserStore();
const activeSystem = ref<SystemType>('bt');
const remark = ref('');
const files = ref<Record<SystemType, UploadedFile[]>>({
  bt: [],
  sy: [],
});

const isAdmin = computed(() => {
  const user = userStore.getUser(activeSystem.value);
  return !!user?.is_superuser;
});

const currentFiles = computed(() => files.value[activeSystem.value]);

const fetchFiles = async (system: SystemType, options?: { silent?: boolean }) => {
  try {
    const res = await userStore.requestWithAuth<{ results: UploadedFile[] }>(system, {
      method: 'get',
      url: '/uploaded-files/',
    });
    files.value[system] = res.results;
  } catch (error) {
    if (!options?.silent) {
      ElMessage.error(`${system.toUpperCase()} 文件列表加载失败`);
    }
    console.error(`${system.toUpperCase()} 文件列表加载失败`, error);
  }
};

const customUpload = async ({ file }: { file: File }) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('name', remark.value || file.name);

  try {
    await userStore.requestWithAuth(activeSystem.value, {
      method: 'post',
      url: '/uploaded-files/',
      data: formData,
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    ElMessage.success('上传成功');
    remark.value = '';
    await fetchFiles(activeSystem.value);
  } catch (error) {
    ElMessage.error('上传失败');
  }
};

const beforeUpload = (file: File) => {
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('文件不能超过10MB');
    return false;
  }
  return true;
};

const downloadFile = async (row: UploadedFile) => {
  try {
    const blob = await userStore.requestWithAuth<Blob>(activeSystem.value, {
      method: 'get',
      url: `/download/${row.id}/`,
      responseType: 'blob',
    });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = row.name;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    ElMessage.error('下载失败');
  }
};

const deleteFile = async (id: number) => {
  try {
    await userStore.requestWithAuth(activeSystem.value, {
      method: 'delete',
      url: `/uploaded-files/${id}/`,
    });
    ElMessage.success('删除成功');
    await fetchFiles(activeSystem.value);
  } catch (error) {
    ElMessage.error('删除失败');
  }
};

onMounted(async () => {
  await Promise.allSettled(SYSTEMS.map((system) => fetchFiles(system, { silent: true })));
});
</script>
