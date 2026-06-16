import axios from 'axios';
import { SYSTEM_LABELS, type SystemType } from '@/utils/systems';

export interface LoginSystemFailure {
  system: SystemType;
  error: unknown;
  apiBase: string;
}

function getHttpStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined;
}

function getApiPort(apiBase: string): string | null {
  try {
    const url = new URL(apiBase);
    if (url.port) {
      return url.port;
    }
    return url.protocol === 'https:' ? '443' : '80';
  } catch {
    return null;
  }
}

function formatSystemFailure({ system, error, apiBase }: LoginSystemFailure): string {
  const label = SYSTEM_LABELS[system];

  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    if (!error.response) {
      const port = getApiPort(apiBase);
      const portText = port ? `${port} 端口、` : '';
      return `${label} 后端无法连接（${apiBase}）。请检查网管电脑 IP、${portText}防火墙、后端容器是否运行，以及 CORS_ALLOWED_ORIGINS 是否包含当前前端地址。`;
    }

    if (status === 400 || status === 403) {
      return `${label} 后端拒绝登录请求（HTTP ${status}）。请检查配置文件 backend/deploy_host_ip.txt，确认新网管 IP 已加入 DJANGO_ALLOWED_HOSTS 和 CORS_ALLOWED_ORIGINS 后重启容器。`;
    }

    if (status === 404) {
      return `${label} 登录接口不存在（HTTP 404）。请检查后端端口和前端 API 地址配置。`;
    }

    if (status && status >= 500) {
      return `${label} 后端服务异常（HTTP ${status}）。请检查后端容器日志。`;
    }

    if (status) {
      return `${label} 登录失败（HTTP ${status}）。`;
    }
  }

  const message = error instanceof Error ? error.message : '未知错误';
  return `${label} 登录失败：${message}`;
}

export function formatLoginFailureMessage(failures: LoginSystemFailure[]): string {
  if (
    failures.length > 0
    && failures.every(({ error }) => getHttpStatus(error) === 401)
  ) {
    return '用户名或密码错误。';
  }

  if (failures.length === 0) {
    return '登录失败，请检查网络连接或账号密码。';
  }

  return failures.map(formatSystemFailure).join('\n');
}
