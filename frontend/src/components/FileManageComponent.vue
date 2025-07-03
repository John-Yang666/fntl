<template>
  <el-card>
    <template #header>文件管理</template>

    <!-- 上传区域（仅管理员可见） -->
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

    <!-- 文件列表 -->
    <el-table :data="files" style="width: 100%">
      <el-table-column prop="name" label="备注名称" />
      <el-table-column prop="upload_time" label="上传时间" />
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button type="success" size="small" @click="downloadFile(row.id)">下载</el-button>
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

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/userStore'

const backendPort = import.meta.env.VITE_BACKEND_PORT
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}`

const userStore = useUserStore()
const token = userStore.token
const userInfo = userStore.user
const isAdmin = userInfo?.groups?.includes('System Admin') || userInfo?.is_superuser || false

if (!token) {
  ElMessage.warning('未登录或登录已过期，请重新登录')
}

const files = ref([])
const remark = ref('')  // 备注字段

const fetchFiles = async () => {
  try {
    const res = await axios.get(`${baseURL}/api/uploaded-files/`)
    files.value = res.data.results
  } catch (e) {
    ElMessage.error('文件列表加载失败')
  }
}

const customUpload = async ({ file }) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('name', remark.value || file.name)

  try {
    await axios.post(`${baseURL}/api/uploaded-files/`, formData, {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'multipart/form-data'
      }
    })
    ElMessage.success('上传成功')
    remark.value = ''
    fetchFiles()
  } catch (e) {
    console.error('上传失败:', e.response?.data || e)
    ElMessage.error('上传失败: ' + (e.response?.data?.detail || '请检查控制台'))
  }
}

const beforeUpload = (file) => {
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('文件不能超过10MB')
    return false
  }
  return true
}

const downloadFile = (id) => {
  window.open(`${baseURL}/api/download/${id}/`, '_blank')
}

const deleteFile = async (id) => {
  try {
    await axios.delete(`${baseURL}/api/uploaded-files/${id}/`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    })
    ElMessage.success('删除成功')
    fetchFiles()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

onMounted(fetchFiles)
</script>
