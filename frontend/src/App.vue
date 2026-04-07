<template>
  <div class="app-shell">
    <!-- 当路径不是 '/login' 或 '/switch-mode/:index' 或 '/restart-command/:index' 时才显示 HeaderComponent -->
    <HeaderComponent v-if="!hideHeader" />
    <router-view></router-view>
  </div>
  <div v-if="isPageLocked" class="manual-page-lock-overlay">
    <div v-if="isUnlockPromptVisible" class="manual-page-lock-panel">
      <div class="manual-page-lock-unlock">
        <div class="manual-page-lock-hint">
          请输入当前登录用户
          <strong>{{ activeUsername || '未知用户' }}</strong>
          的登录密码以解除锁定
        </div>
        <input
          v-model="unlockPassword"
          type="password"
          class="manual-page-lock-input"
          placeholder="请输入登录密码"
          @keydown.enter.prevent="submitUnlock"
        />
        <div v-if="unlockErrorMessage" class="manual-page-lock-error">
          {{ unlockErrorMessage }}
        </div>
        <div class="manual-page-lock-actions">
          <button
            type="button"
            class="manual-page-lock-action secondary"
            @click="cancelUnlockPrompt"
          >
            取消
          </button>
          <button
            type="button"
            class="manual-page-lock-action primary"
            :disabled="isUnlocking"
            @click="submitUnlock"
          >
            {{ isUnlocking ? '验证中...' : '验证并解锁' }}
          </button>
        </div>
      </div>
    </div>
  </div>
  <button
    type="button"
    class="page-lock-toggle-button"
    :title="isPageLocked ? '点击解除当前页面锁定' : '点击锁定当前页面，防止误操作'"
    @click="togglePageLock"
  >
    {{ pageLockButtonLabel }}
  </button>
</template>

<script lang="ts" setup>
import axios from 'axios';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import HeaderComponent from '@/components/HeaderComponent.vue';
import { useUserStore } from '@/stores/userStore';
import { SYSTEMS, getApiBase, type SystemType } from '@/utils/systems';

// 获取当前路由
const route = useRoute();
const userStore = useUserStore();

// 计算属性：判断当前路径是否需要隐藏 HeaderComponent
const hideHeader = computed(() => route.matched.some((record) => record.meta.hideHeader));

const BLOCKING_OVERLAY_SELECTOR = 'body > .v-modal, body > .el-loading-mask';
const OVERLAY_CONTENT_SELECTOR = '.el-dialog, .el-drawer, .el-message-box, .el-loading-spinner, .el-loading-text';
const DIALOG_LIKE_SELECTOR = '.el-dialog, .el-drawer, .el-message-box, [role="dialog"], [aria-modal="true"]';
const PAGE_LOCK_STORAGE_KEY = 'manual_page_lock';
let cleanupTimer: number | null = null;
let overlayCleanupInterval: number | null = null;
let overlayObserver: MutationObserver | null = null;
const isPageLocked = ref(false);
const pageLockButtonLabel = computed(() => (isPageLocked.value ? '解除锁定' : '页面锁定'));
const isUnlockPromptVisible = ref(false);
const unlockPassword = ref('');
const unlockErrorMessage = ref('');
const isUnlocking = ref(false);
const activeUsername = computed(() => {
  const usernames = new Set(
    SYSTEMS.map((system) => userStore.getUser(system)?.username).filter((value): value is string => !!value),
  );

  return usernames.size === 1 ? Array.from(usernames)[0] : userStore.user?.username ?? '';
});

const isVisibleElement = (element: Element | null) => {
  if (!(element instanceof HTMLElement)) {
    return false;
  }

  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();

  return (
    style.display !== 'none' &&
    style.visibility !== 'hidden' &&
    style.opacity !== '0' &&
    rect.width > 0 &&
    rect.height > 0
  );
};

const parseAlpha = (color: string) => {
  const rgbaMatch = color.match(/rgba\((?:\d+\s*,\s*){3}([0-9.]+)\)/i);
  if (rgbaMatch) {
    return Number.parseFloat(rgbaMatch[1]);
  }

  if (/^rgb\(/i.test(color)) {
    return 1;
  }

  return 0;
};

const isDarkBackdrop = (color: string) => {
  const rgbaMatch = color.match(/rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (!rgbaMatch) {
    return false;
  }

  const [r, g, b] = rgbaMatch.slice(1, 4).map((value) => Number.parseInt(value, 10));
  return r < 90 && g < 90 && b < 90;
};

const isSuspiciousViewportBlocker = (element: HTMLElement) => {
  if (
    element.id === 'app' ||
    element.classList.contains('manual-page-lock-overlay') ||
    element.classList.contains('manual-page-lock-panel') ||
    element.classList.contains('page-lock-toggle-button') ||
    element.matches(DIALOG_LIKE_SELECTOR) ||
    element.closest(DIALOG_LIKE_SELECTOR)
  ) {
    return false;
  }

  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const backgroundColor = style.backgroundColor || '';
  const alpha = parseAlpha(backgroundColor);
  const coversViewport =
    rect.width >= viewportWidth * 0.9 &&
    rect.height >= viewportHeight * 0.85 &&
    rect.top <= 8 &&
    rect.left <= 8;

  return (
    coversViewport &&
    (style.position === 'fixed' || style.position === 'absolute') &&
    style.pointerEvents !== 'none' &&
    alpha >= 0.2 &&
    isDarkBackdrop(backgroundColor)
  );
};

const describeElement = (element: HTMLElement) => {
  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();

  return {
    tag: element.tagName.toLowerCase(),
    id: element.id || null,
    className: element.className || null,
    zIndex: style.zIndex || null,
    position: style.position,
    backgroundColor: style.backgroundColor,
    pointerEvents: style.pointerEvents,
    rect: {
      top: Math.round(rect.top),
      left: Math.round(rect.left),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    },
  };
};

const clearRootInteractivityLocks = () => {
  const rootCandidates = [
    document.documentElement,
    document.body,
    document.querySelector<HTMLElement>('#app'),
    document.querySelector<HTMLElement>('.app-shell'),
  ].filter((node): node is HTMLElement => !!node);

  rootCandidates.forEach((node) => {
    node.removeAttribute('inert');
    node.removeAttribute('aria-hidden');
    if ((node as HTMLElement & { inert?: boolean }).inert) {
      (node as HTMLElement & { inert?: boolean }).inert = false;
    }
  });

  Array.from(document.body.children).forEach((child) => {
    if (!(child instanceof HTMLElement)) {
      return;
    }
    if (child.matches('.el-overlay, .v-modal, .el-loading-mask')) {
      return;
    }

    child.removeAttribute('inert');
    child.removeAttribute('aria-hidden');
    if ((child as HTMLElement & { inert?: boolean }).inert) {
      (child as HTMLElement & { inert?: boolean }).inert = false;
    }
  });
};

const cleanupOrphanedOverlays = () => {
  if (typeof window === 'undefined') {
    return;
  }

  const overlays = Array.from(document.querySelectorAll<HTMLElement>(BLOCKING_OVERLAY_SELECTOR));

  overlays.forEach((overlay) => {
    if (overlay.classList.contains('el-loading-mask')) {
      overlay.remove();
      return;
    }

    const overlayContent = Array.from(
      overlay.querySelectorAll<HTMLElement>(OVERLAY_CONTENT_SELECTOR),
    );
    const hasDialogLikeContent = overlayContent.some((content) => content.matches(DIALOG_LIKE_SELECTOR));
    const hasVisibleContent = overlayContent.some((content) => isVisibleElement(content));

    // Element Plus 的 MessageBox / Dialog 在入场过渡的极短窗口内可能还不可见。
    // 这里只清理“既没有可见内容，也没有对话框内容”的遮罩，避免误删正常弹窗。
    if (!hasVisibleContent && !hasDialogLikeContent) {
      overlay.remove();
    }
  });

  const suspiciousBlockers = Array.from(document.querySelectorAll<HTMLElement>('body *')).filter(
    (element) => isSuspiciousViewportBlocker(element),
  );

  if (suspiciousBlockers.length > 0) {
    const blockerSummaries = suspiciousBlockers.map((element) => describeElement(element));
    const snapshot = JSON.stringify({
      capturedAt: new Date().toISOString(),
      blockers: blockerSummaries,
    });
    sessionStorage.setItem('overlay_debug_snapshot', snapshot);
    localStorage.setItem('overlay_debug_snapshot', snapshot);

    suspiciousBlockers.forEach((element) => {
      element.style.setProperty('display', 'none', 'important');
      element.style.setProperty('pointer-events', 'none', 'important');
    });
  }

  const hasVisibleBlockingOverlay = Array.from(
    document.querySelectorAll<HTMLElement>(BLOCKING_OVERLAY_SELECTOR),
  ).some((overlay) => {
    if (overlay.classList.contains('el-loading-mask')) {
      return false;
    }

    const overlayContent = Array.from(
      overlay.querySelectorAll<HTMLElement>(OVERLAY_CONTENT_SELECTOR),
    );

    return (
      overlayContent.some((content) => content.matches(DIALOG_LIKE_SELECTOR)) ||
      overlayContent.some((content) => isVisibleElement(content))
    );
  });

  if (!hasVisibleBlockingOverlay) {
    document.body.classList.remove('el-popup-parent--hidden', 'el-loading-parent--hidden');
    document.documentElement.classList.remove('el-popup-parent--hidden', 'el-loading-parent--hidden');

    if (document.body.style.overflow === 'hidden') {
      document.body.style.overflow = '';
    }
    if (document.documentElement.style.overflow === 'hidden') {
      document.documentElement.style.overflow = '';
    }
    if (document.body.style.width) {
      document.body.style.width = '';
    }
  }

  clearRootInteractivityLocks();
};

const scheduleOverlayCleanup = () => {
  if (cleanupTimer !== null) {
    window.clearTimeout(cleanupTimer);
  }

  cleanupTimer = window.setTimeout(() => {
    cleanupTimer = null;
    cleanupOrphanedOverlays();
  }, 80);
};

const handlePageShow = () => {
  scheduleOverlayCleanup();
};

const handleVisibilityChange = () => {
  if (document.visibilityState === 'visible') {
    scheduleOverlayCleanup();
  }
};

const handlePageHide = () => {
  cleanupOrphanedOverlays();
};

const syncPageLockState = () => {
  sessionStorage.setItem(PAGE_LOCK_STORAGE_KEY, isPageLocked.value ? 'true' : 'false');
};

const resetUnlockPrompt = () => {
  isUnlockPromptVisible.value = false;
  unlockPassword.value = '';
  unlockErrorMessage.value = '';
  isUnlocking.value = false;
};

const unlockPage = () => {
  cleanupOrphanedOverlays();
  isPageLocked.value = false;
  syncPageLockState();
  resetUnlockPrompt();
};

const cancelUnlockPrompt = () => {
  resetUnlockPrompt();
};

const verifyUnlockPassword = async (password: string) => {
  const systemsToVerify = SYSTEMS.filter((system) => !!userStore.getUser(system)?.username);

  if (systemsToVerify.length === 0 || !activeUsername.value) {
    throw new Error('当前用户信息缺失，请重新登录后再解锁。');
  }

  const verificationResults = await Promise.allSettled(
    systemsToVerify.map(async (system) => {
      await axios.post(`${getApiBase(system)}/token/`, {
        username: activeUsername.value,
        password,
      });
      return system;
    }),
  );

  const failedSystems = verificationResults
    .map((result, index) => ({ result, system: systemsToVerify[index] }))
    .filter(({ result }) => result.status === 'rejected')
    .map(({ system }) => system.toUpperCase());

  if (failedSystems.length > 0) {
    throw new Error(`密码验证失败: ${failedSystems.join(', ')}`);
  }
};

const submitUnlock = async () => {
  if (!unlockPassword.value) {
    unlockErrorMessage.value = '请输入登录密码。';
    return;
  }

  unlockErrorMessage.value = '';
  isUnlocking.value = true;

  try {
    await verifyUnlockPassword(unlockPassword.value);
    unlockPage();
  } catch (error) {
    unlockErrorMessage.value = error instanceof Error ? error.message : '密码验证失败，请重试。';
  } finally {
    isUnlocking.value = false;
  }
};

const togglePageLock = () => {
  if (isPageLocked.value) {
    isUnlockPromptVisible.value = !isUnlockPromptVisible.value;
    unlockErrorMessage.value = '';
    return;
  }

  isPageLocked.value = true;
  syncPageLockState();
  resetUnlockPrompt();
};

watch(
  () => route.fullPath,
  async () => {
    await nextTick();
    scheduleOverlayCleanup();
  },
);

onMounted(() => {
  isPageLocked.value = sessionStorage.getItem(PAGE_LOCK_STORAGE_KEY) === 'true';
  if (!isPageLocked.value) {
    resetUnlockPrompt();
  }
  scheduleOverlayCleanup();
  (window as Window & { __btNmsClearBlockers?: () => void }).__btNmsClearBlockers = cleanupOrphanedOverlays;
  window.addEventListener('pageshow', handlePageShow);
  window.addEventListener('pagehide', handlePageHide);
  window.addEventListener('beforeunload', handlePageHide);
  document.addEventListener('visibilitychange', handleVisibilityChange);

  overlayObserver = new MutationObserver(() => {
    scheduleOverlayCleanup();
  });

  overlayObserver.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'style'],
  });

  overlayCleanupInterval = window.setInterval(() => {
    cleanupOrphanedOverlays();
  }, 1000);
});

onBeforeUnmount(() => {
  if (cleanupTimer !== null) {
    window.clearTimeout(cleanupTimer);
    cleanupTimer = null;
  }
  if (overlayCleanupInterval !== null) {
    window.clearInterval(overlayCleanupInterval);
    overlayCleanupInterval = null;
  }
  if (overlayObserver) {
    overlayObserver.disconnect();
    overlayObserver = null;
  }
  delete (window as Window & { __btNmsClearBlockers?: () => void }).__btNmsClearBlockers;

  window.removeEventListener('pageshow', handlePageShow);
  window.removeEventListener('pagehide', handlePageHide);
  window.removeEventListener('beforeunload', handlePageHide);
  document.removeEventListener('visibilitychange', handleVisibilityChange);
});
</script>

<style scoped>
.app-shell {
  width: 100%;
  max-width: 100%;
  overflow-x: hidden;
}

.page-lock-toggle-button {
  position: fixed;
  right: 16px;
  top: 14px;
  z-index: 2147483647;
  border: none;
  border-radius: 999px;
  background: #111827;
  color: #fff;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  cursor: pointer;
  opacity: 0.88;
}

.page-lock-toggle-button:hover {
  opacity: 1;
}

.manual-page-lock-overlay {
  position: fixed;
  inset: 0;
  z-index: 2147483646;
  background: rgba(17, 24, 39, 0.18);
  cursor: not-allowed;
}

.manual-page-lock-panel {
  position: absolute;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(17, 24, 39, 0.9);
  color: #fff;
  font-size: 13px;
  line-height: 1.4;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
  user-select: none;
  min-width: 320px;
  max-width: min(420px, calc(100vw - 32px));
}

.manual-page-lock-unlock {
  margin-top: 0;
}

.manual-page-lock-hint {
  margin-bottom: 10px;
  color: rgba(255, 255, 255, 0.92);
}

.manual-page-lock-input {
  width: 100%;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  padding: 10px 12px;
  outline: none;
}

.manual-page-lock-input::placeholder {
  color: rgba(255, 255, 255, 0.58);
}

.manual-page-lock-error {
  margin-top: 8px;
  color: #fecaca;
}

.manual-page-lock-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

.manual-page-lock-action {
  border: none;
  border-radius: 999px;
  padding: 8px 12px;
  cursor: pointer;
}

.manual-page-lock-action.primary {
  background: #22c55e;
  color: #052e16;
}

.manual-page-lock-action.primary:disabled {
  cursor: wait;
  opacity: 0.72;
}

.manual-page-lock-action.secondary {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}
</style>

<style>
body > .v-modal:not(:has(.el-dialog, .el-drawer, .el-message-box)),
body > .el-loading-mask {
  display: none !important;
  pointer-events: none !important;
}

body.el-loading-parent--hidden {
  overflow: auto !important;
  width: auto !important;
}

html.el-loading-parent--hidden {
  overflow: auto !important;
}
</style>
