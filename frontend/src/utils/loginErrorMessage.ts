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

function formatSystemFailure({ system, error, apiBase }: LoginSystemFailure): string {
  const label = SYSTEM_LABELS[system];

  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    if (!error.response) {
      return `${label} 后端无法连接（${apiBase}）。请检查前端代理配置、共享 Docker 网络、防火墙和后端容器是否运行。`;
    }

    if (status === 400 || status === 403) {
      return `${label} 后端拒绝登录请求（HTTP ${status}）。请检查配置文件 deploy_host_ip.txt，确认新网管 IP 已加入 DJANGO_ALLOWED_HOSTS，并检查前端代理 Host 头配置后重启容器。`;
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
