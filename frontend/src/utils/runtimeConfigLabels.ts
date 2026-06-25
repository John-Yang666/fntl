const MODEL_LABELS: Record<string, string> = {
  RawFrameLog: '原始报文日志',
  SwitchData: '开关量数据',
  AnalogData: '电压电流数据',
  ChangeBitEvent: '变位事件',
  AlarmData: '历史告警记录',
  RelayAction: '继电器动作记录',
  UserOperation: '用户操作记录',
};

const FIELD_LABELS: Record<string, string> = {
  'Access Token 有效期（天）': '访问令牌有效期（天）',
  'Refresh Token 有效期（天）': '刷新令牌有效期（天）',
};

const TEXT_LABELS: Record<string, string> = {
  'Token 有效期参数': '令牌有效期参数',
};

export function translateRuntimeConfigText(text: string): string {
  const translated = Object.entries(MODEL_LABELS).reduce(
    (result, [source, target]) => result.replaceAll(source, target),
    text,
  );
  const translatedText = Object.entries(TEXT_LABELS).reduce(
    (result, [source, target]) => result.replaceAll(source, target),
    translated,
  );
  return translatedText.replace(/(原始报文日志|开关量数据|电压电流数据|变位事件|历史告警记录|继电器动作记录|用户操作记录):\s*/g, '$1：');
}

export function getCleanupModelLabel(label: string): string {
  const modelName = label.replace(/\s*保留天数$/, '').trim();
  return translateRuntimeConfigText(modelName);
}

export function getRuntimeConfigFieldLabel(label: string): string {
  return FIELD_LABELS[label] || translateRuntimeConfigText(label);
}

export function formatCleanupDaysDefault(value: unknown): string {
  if (typeof value === 'number') {
    return `默认：${value} 天`;
  }
  if (typeof value === 'string' && value.trim()) {
    return `默认：${value} 天`;
  }
  return '默认：-';
}

export function hasDaysUnit(label: string): boolean {
  return /（天）|\(天\)|天$/.test(label);
}

export function formatRuntimeConfigDefault(label: string, value: unknown): string {
  const suffix = hasDaysUnit(label) ? ' 天' : '';
  if (typeof value === 'number') {
    return `默认：${value}${suffix}`;
  }
  if (typeof value === 'string') {
    return `默认：${value}${value.trim() ? suffix : ''}`;
  }
  return '默认：-';
}
