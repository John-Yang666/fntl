import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus/es/components/message/index.mjs';
import { useUserStore } from '@/stores/userStore';
import {
  SYSTEMS,
  buildAuthWebSocketProtocols,
  getWsBase,
  type SystemType,
} from '@/utils/systems';

export interface AlarmSnapshot {
  type: 'alarm.snapshot';
  system: SystemType;
  revision: number;
  current_count: number;
  current_unconfirmed_count: number;
  historical_unconfirmed_count: number;
  total_unconfirmed_count: number;
  should_play: boolean;
  audible_occurrence_ids: string[];
  reason?: string;
}

interface CurrentAlarmResponse {
  id: string;
  confirmed: boolean;
}

interface HistoricalAlarmResponse {
  id: string;
}

interface Page<T> {
  next: string | null;
  results: T[];
}

const ALARM_STATE_CHANGED_EVENT = 'alarm-state-changed';
const SILENCED_IDS_KEY = 'silencedAlarmOccurrenceIds';
const SOUND_ENABLED_KEY = 'soundEnabled';
const ALARM_SNAPSHOT_POLL_INTERVAL_MS = 10_000;

export function useAlarmSound() {
  const route = useRoute();
  const userStore = useUserStore();
  const snapshots = ref<Record<SystemType, AlarmSnapshot | null>>({ bt: null, sy: null });
  const soundEnabled = ref(true);
  const isTestingSound = ref(false);
  const pendingPlayback = ref(false);
  const audioPrimed = ref(false);
  const sockets: Record<SystemType, WebSocket | null> = { bt: null, sy: null };
  const reconnectTimers: Record<SystemType, ReturnType<typeof setTimeout> | null> = { bt: null, sy: null };
  const reconnectAttempts: Record<SystemType, number> = { bt: 0, sy: 0 };
  let alarmAudio: HTMLAudioElement | null = null;
  let testAudio: HTMLAudioElement | null = null;
  let mounted = false;
  let autoplayWarning: { close: () => void } | null = null;
  let snapshotPollTimer: ReturnType<typeof setInterval> | null = null;

  const audibleOccurrenceIds = computed(() =>
    SYSTEMS.flatMap((system) =>
      (snapshots.value[system]?.audible_occurrence_ids ?? []).map((id) => `${system}:${id}`),
    ),
  );
  const totalUnconfirmed = computed(() =>
    SYSTEMS.reduce((total, system) => total + (snapshots.value[system]?.total_unconfirmed_count ?? 0), 0),
  );
  const hasAlerts = computed(() => totalUnconfirmed.value > 0);
  const activeAlertsTabLabel = computed(() =>
    totalUnconfirmed.value > 0 ? `告警详情（待确认 ${totalUnconfirmed.value}）` : '告警详情',
  );
  const canPlay = () => mounted && !route.matched.some((record) => record.meta.hideHeader);

  const getAlarmAudio = () => {
    if (!alarmAudio) {
      alarmAudio = new Audio('/audio/alert.mp3');
      alarmAudio.loop = true;
      alarmAudio.preload = 'auto';
    }
    return alarmAudio;
  };

  const closeAutoplayWarning = () => {
    autoplayWarning?.close();
    autoplayWarning = null;
  };

  const openAutoplayWarning = () => {
    if (!canPlay() || autoplayWarning) return;
    autoplayWarning = ElMessage({
      type: 'warning',
      message: '请先在页面内点击任意位置启用告警声',
      duration: 0,
      showClose: true,
      onClose: () => { autoplayWarning = null; },
    });
  };

  const stopAlarmSound = () => {
    if (alarmAudio) {
      alarmAudio.pause();
      alarmAudio.currentTime = 0;
    }
    pendingPlayback.value = false;
    closeAutoplayWarning();
  };

  const playAlarmSound = async () => {
    if (!canPlay() || !soundEnabled.value) return;
    const audio = getAlarmAudio();
    if (!audio.paused && !audio.ended) return;
    try {
      await audio.play();
      pendingPlayback.value = false;
      closeAutoplayWarning();
    } catch (error) {
      pendingPlayback.value = true;
      console.warn('自动播放告警声失败，等待用户交互', error);
      openAutoplayWarning();
    }
  };

  const loadSilencedIds = () => {
    try {
      const value = JSON.parse(sessionStorage.getItem(SILENCED_IDS_KEY) ?? '[]');
      return new Set<string>(Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []);
    } catch {
      return new Set<string>();
    }
  };

  const reconcileSound = () => {
    const audible = audibleOccurrenceIds.value;
    if (audible.length === 0) {
      sessionStorage.removeItem(SILENCED_IDS_KEY);
      stopAlarmSound();
      return;
    }
    const silenced = loadSilencedIds();
    if (audible.every((id) => silenced.has(id))) {
      stopAlarmSound();
      return;
    }
    if (soundEnabled.value) void playAlarmSound();
  };

  const pauseAlerts = () => {
    sessionStorage.setItem(SILENCED_IDS_KEY, JSON.stringify(audibleOccurrenceIds.value));
    stopAlarmSound();
  };

  const primeAudio = async () => {
    if (!canPlay() || !soundEnabled.value) return false;
    const audio = getAlarmAudio();
    if (!audio.paused) return true;
    const wasMuted = audio.muted;
    audio.muted = true;
    try {
      await audio.play();
      audio.pause();
      audio.currentTime = 0;
      audioPrimed.value = true;
      return true;
    } catch {
      audioPrimed.value = false;
      return false;
    } finally {
      audio.muted = wasMuted;
    }
  };

  const handleInteraction = async () => {
    if (!pendingPlayback.value && audioPrimed.value) return;
    if (await primeAudio()) reconcileSound();
  };

  const toggleSound = () => {
    localStorage.setItem(SOUND_ENABLED_KEY, JSON.stringify(soundEnabled.value));
    if (soundEnabled.value) {
      void primeAudio().then(reconcileSound);
    } else {
      stopAlarmSound();
    }
  };

  const toggleTestSound = async () => {
    if (!soundEnabled.value) {
      ElMessage.warning('请先打开声音开关再测试告警声');
      return;
    }
    if (!testAudio) {
      testAudio = new Audio('/audio/alert.mp3');
      testAudio.loop = true;
    }
    if (isTestingSound.value) {
      testAudio.pause();
      testAudio.currentTime = 0;
      isTestingSound.value = false;
      return;
    }
    try {
      await testAudio.play();
      isTestingSound.value = true;
    } catch {
      ElMessage.warning('浏览器限制了播放，请先在页面内点击一次后再试音');
    }
  };

  const applySnapshot = (system: SystemType, snapshot: AlarmSnapshot) => {
    const previous = snapshots.value[system];
    if (previous && snapshot.revision < previous.revision) return;
    snapshots.value = { ...snapshots.value, [system]: snapshot };
    window.dispatchEvent(new CustomEvent(ALARM_STATE_CHANGED_EVENT, { detail: snapshot }));
    reconcileSound();
  };

  const fetchAllHistoricalOccurrenceIds = async (system: SystemType) => {
    const ids: string[] = [];
    let url: string | null = '/alerts/?is_confirmed=false&monitored=true&page_size=500';
    while (url) {
      const page: Page<HistoricalAlarmResponse> = await userStore.requestWithAuth(system, {
        method: 'get',
        url,
      });
      ids.push(...page.results.map((item) => item.id));
      url = page.next;
    }
    return ids;
  };

  const refreshSnapshotFromApi = async (system: SystemType) => {
    if (!userStore.auth[system].token) return;
    try {
      const [current, historicalIds] = await Promise.all([
        userStore.requestWithAuth<CurrentAlarmResponse[]>(system, {
          method: 'get',
          url: '/active-alarms/',
        }),
        fetchAllHistoricalOccurrenceIds(system),
      ]);
      const currentIds = current.filter((item) => !item.confirmed).map((item) => item.id);
      applySnapshot(system, {
        type: 'alarm.snapshot',
        system,
        revision: snapshots.value[system]?.revision ?? 0,
        current_count: current.length,
        current_unconfirmed_count: currentIds.length,
        historical_unconfirmed_count: historicalIds.length,
        total_unconfirmed_count: currentIds.length + historicalIds.length,
        should_play: currentIds.length + historicalIds.length > 0,
        audible_occurrence_ids: [...currentIds, ...historicalIds],
        reason: 'alarm.poll',
      });
    } catch (error) {
      console.warn(`${system.toUpperCase()} 告警状态轮询失败`, error);
    }
  };

  const refreshSnapshotsFromApi = () => {
    SYSTEMS.forEach((system) => { void refreshSnapshotFromApi(system); });
  };

  const scheduleReconnect = (system: SystemType) => {
    if (!mounted || !userStore.auth[system].token || reconnectTimers[system]) return;
    const delay = Math.min(30_000, 1_000 * (2 ** reconnectAttempts[system]));
    reconnectAttempts[system] += 1;
    reconnectTimers[system] = setTimeout(() => {
      reconnectTimers[system] = null;
      connect(system);
    }, delay);
  };

  const connect = (system: SystemType) => {
    const token = userStore.auth[system].token;
    const existing = sockets[system];
    if (!mounted || !token || existing?.readyState === WebSocket.OPEN || existing?.readyState === WebSocket.CONNECTING) return;
    const socket = new WebSocket(`${getWsBase(system)}/alarms/`, buildAuthWebSocketProtocols(token));
    sockets[system] = socket;
    socket.onopen = () => { reconnectAttempts[system] = 0; };
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as AlarmSnapshot | { type?: string };
        if (payload.type === 'alarm.ping') {
          socket.send(JSON.stringify({ type: 'alarm.pong' }));
          return;
        }
        if (payload.type !== 'alarm.snapshot') return;
        const snapshot = payload as AlarmSnapshot;
        applySnapshot(system, snapshot);
      } catch (error) {
        console.warn(`${system.toUpperCase()} 告警 WebSocket 消息无效`, error);
      }
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (sockets[system] === socket) sockets[system] = null;
      scheduleReconnect(system);
    };
  };

  const disconnect = (system: SystemType) => {
    if (reconnectTimers[system]) clearTimeout(reconnectTimers[system]);
    reconnectTimers[system] = null;
    const socket = sockets[system];
    sockets[system] = null;
    socket?.close();
  };

  watch(
    () => SYSTEMS.map((system) => userStore.auth[system].token),
    () => {
      SYSTEMS.forEach((system) => {
        disconnect(system);
        snapshots.value = { ...snapshots.value, [system]: null };
        if (userStore.auth[system].token) connect(system);
      });
      refreshSnapshotsFromApi();
    },
  );

  onMounted(() => {
    mounted = true;
    const stored = localStorage.getItem(SOUND_ENABLED_KEY);
    soundEnabled.value = stored === null ? true : JSON.parse(stored);
    localStorage.setItem(SOUND_ENABLED_KEY, JSON.stringify(soundEnabled.value));
    window.addEventListener('pointerdown', handleInteraction, true);
    window.addEventListener('keydown', handleInteraction, true);
    window.addEventListener('focus', handleInteraction);
    SYSTEMS.forEach(connect);
    refreshSnapshotsFromApi();
    snapshotPollTimer = setInterval(refreshSnapshotsFromApi, ALARM_SNAPSHOT_POLL_INTERVAL_MS);
    if (soundEnabled.value) void primeAudio();
  });

  onBeforeUnmount(() => {
    mounted = false;
    SYSTEMS.forEach(disconnect);
    if (snapshotPollTimer) clearInterval(snapshotPollTimer);
    stopAlarmSound();
    testAudio?.pause();
    window.removeEventListener('pointerdown', handleInteraction, true);
    window.removeEventListener('keydown', handleInteraction, true);
    window.removeEventListener('focus', handleInteraction);
  });

  return {
    activeAlertsTabLabel,
    hasAlerts,
    isTestingSound,
    pauseAlerts,
    soundEnabled,
    toggleSound,
    toggleTestSound,
  };
}
