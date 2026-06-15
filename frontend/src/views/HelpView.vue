<template>
  <div class="help-page" data-testid="help-view">
    <el-container>
      <el-header>
        <h1>感谢您的使用！</h1>
      </el-header>
      <el-main>
        <el-card class="box-card">
          <template #header>
            <div class="faq-header">
              <span class="clearfix">常见问题解答</span>
              <el-button
                v-if="canEditFaq"
                type="primary"
                size="small"
                @click="openEditor"
              >
                编辑 FAQ
              </el-button>
            </div>
          </template>
          <el-skeleton :loading="faqLoading" animated>
            <template #template>
              <el-skeleton-item variant="text" style="width: 60%" />
              <el-skeleton-item variant="text" style="width: 100%" />
              <el-skeleton-item variant="text" style="width: 90%" />
            </template>
            <el-empty v-if="faqItems.length === 0" description="暂无 FAQ 内容" />
            <el-collapse v-else>
              <el-collapse-item
                v-for="item in faqItems"
                :key="item.id"
                :title="item.title"
                :name="String(item.id)"
              >
                <div class="faq-content">{{ item.content }}</div>
              </el-collapse-item>
            </el-collapse>
          </el-skeleton>
        </el-card>

        <el-dialog
          v-model="editorVisible"
          width="720px"
          destroy-on-close
        >
          <template #header>
            <div class="faq-dialog-header">
              <span>编辑 FAQ</span>
              <div class="faq-dialog-header-actions">
                <el-button @click="editorVisible = false">取消</el-button>
                <el-button type="primary" :loading="faqSaving" @click="saveFaq">保存</el-button>
              </div>
            </div>
          </template>
          <div class="faq-editor-toolbar">
            <el-button type="primary" plain @click="addFaqItem">新增问题</el-button>
          </div>
          <div v-if="draftFaqItems.length === 0" class="faq-empty-tip">当前没有 FAQ，点击“新增问题”开始编辑。</div>
          <div
            v-for="(item, index) in draftFaqItems"
            :key="item.localKey"
            class="faq-edit-card"
          >
            <div class="faq-edit-header">
              <span>问题 {{ index + 1 }}</span>
              <div class="faq-edit-actions">
                <el-button size="small" @click="moveFaqItem(index, -1)" :disabled="index === 0">上移</el-button>
                <el-button size="small" @click="moveFaqItem(index, 1)" :disabled="index === draftFaqItems.length - 1">下移</el-button>
                <el-button size="small" type="danger" plain @click="removeFaqItem(index)">删除</el-button>
              </div>
            </div>
            <el-input
              v-model="item.title"
              placeholder="请输入问题标题"
              class="faq-edit-title"
            />
            <el-input
              v-model="item.content"
              type="textarea"
              :rows="6"
              placeholder="请输入回答内容，支持换行"
            />
          </div>
        </el-dialog>

        <el-card class="box-card">
          <template #header>
            <div class="clearfix">联系方式</div>
          </template>
          <p>如果您有任何问题，请通过以下方式联系我们：</p>
          <ul>
            <li>电子邮件: btserver001@163.com</li>
          </ul>
        </el-card>
      </el-main>
    </el-container>
  </div>
  <div>
    <FileManageComponent />
  </div>
  <FooterComponent />
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue';
  import { ElMessage } from 'element-plus/es/components/message/index.mjs';
  import FooterComponent from '@/components/FooterComponent.vue';
  import FileManageComponent from '@/components/FileManageComponent.vue';
  import { useUserStore } from '@/stores/userStore';

  interface FaqItem {
    id: number;
    title: string;
    content: string;
    display_order: number;
    updated_at: string;
  }

  interface FaqDraftItem {
    id?: number;
    title: string;
    content: string;
    localKey: string;
  }

  const userStore = useUserStore();
  const faqItems = ref<FaqItem[]>([]);
  const faqLoading = ref(false);
  const faqSaving = ref(false);
  const editorVisible = ref(false);
  const draftFaqItems = ref<FaqDraftItem[]>([]);

  const canEditFaq = computed(() => !!userStore.getUser('bt')?.is_superuser);

  function makeLocalKey(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function toDraftItem(item?: Partial<FaqItem>): FaqDraftItem {
    return {
      id: item?.id,
      title: item?.title ?? '',
      content: item?.content ?? '',
      localKey: makeLocalKey(),
    };
  }

  async function loadFaq(): Promise<void> {
    faqLoading.value = true;
    try {
      faqItems.value = await userStore.requestWithAuth<FaqItem[]>('bt', {
        method: 'get',
        url: '/help-faq/',
      });
    } catch (error) {
      console.error('加载 FAQ 失败', error);
      ElMessage.error('FAQ 加载失败');
    } finally {
      faqLoading.value = false;
    }
  }

  function openEditor(): void {
    draftFaqItems.value = faqItems.value.map((item) => toDraftItem(item));
    editorVisible.value = true;
  }

  function addFaqItem(): void {
    draftFaqItems.value.push(toDraftItem());
  }

  function removeFaqItem(index: number): void {
    draftFaqItems.value.splice(index, 1);
  }

  function moveFaqItem(index: number, offset: number): void {
    const targetIndex = index + offset;
    if (targetIndex < 0 || targetIndex >= draftFaqItems.value.length) {
      return;
    }
    const items = [...draftFaqItems.value];
    const [current] = items.splice(index, 1);
    items.splice(targetIndex, 0, current);
    draftFaqItems.value = items;
  }

  async function saveFaq(): Promise<void> {
    const payload = draftFaqItems.value.map(({ id, title, content }) => ({
      ...(id ? { id } : {}),
      title: title.trim(),
      content: content.trim(),
    }));

    if (payload.some((item) => !item.title)) {
      ElMessage.warning('每条 FAQ 都需要填写标题');
      return;
    }

    faqSaving.value = true;
    try {
      faqItems.value = await userStore.requestWithAuth<FaqItem[]>('bt', {
        method: 'put',
        url: '/help-faq/',
        data: payload,
      });
      editorVisible.value = false;
      ElMessage.success('FAQ 已保存');
    } catch (error) {
      console.error('保存 FAQ 失败', error);
      ElMessage.error('FAQ 保存失败');
    } finally {
      faqSaving.value = false;
    }
  }

  onMounted(() => {
    loadFaq();
  });
</script>

<style scoped>
.help-page {
  padding: 20px;
}
h1 {
  color: #2c3e50;
  text-align: center;
}
.box-card {
  margin-bottom: 20px;
}
.clearfix {
  font-size: 18px;
  font-weight: bold;
}
.faq-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.faq-content {
  white-space: pre-line;
  line-height: 1.7;
}
.faq-editor-toolbar {
  margin-bottom: 12px;
}
.faq-edit-card {
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}
.faq-edit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.faq-edit-actions {
  display: flex;
  gap: 8px;
}
.faq-edit-title {
  margin-bottom: 12px;
}
.faq-empty-tip {
  color: #6b7280;
  margin-bottom: 12px;
}
.faq-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.faq-dialog-header-actions {
  display: flex;
  gap: 8px;
}
</style>
