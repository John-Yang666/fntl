import {
  formatCleanupDaysDefault,
  formatRuntimeConfigDefault,
  getCleanupModelLabel,
  getRuntimeConfigFieldLabel,
  hasDaysUnit,
  translateRuntimeConfigText,
} from '../runtimeConfigLabels';

describe('runtime config labels', () => {
  it('translates cleanup model names to Chinese labels', () => {
    expect(getCleanupModelLabel('SwitchData 保留天数')).toBe('开关量数据');
    expect(getCleanupModelLabel('AnalogData 保留天数')).toBe('电压电流数据');
    expect(getCleanupModelLabel('AlarmData 保留天数')).toBe('历史告警记录');
    expect(getCleanupModelLabel('RelayAction 保留天数')).toBe('继电器动作记录');
    expect(getCleanupModelLabel('UserOperation 保留天数')).toBe('用户操作记录');
    expect(getCleanupModelLabel('RawFrameLog 保留天数')).toBe('原始报文日志');
    expect(getCleanupModelLabel('ChangeBitEvent 保留天数')).toBe('变位事件');
  });

  it('adds days unit to cleanup retention defaults', () => {
    expect(formatCleanupDaysDefault(3)).toBe('默认：3 天');
    expect(formatCleanupDaysDefault(30)).toBe('默认：30 天');
  });

  it('translates token field labels to Chinese', () => {
    expect(getRuntimeConfigFieldLabel('Access Token 有效期（天）')).toBe('访问令牌有效期（天）');
    expect(getRuntimeConfigFieldLabel('Refresh Token 有效期（天）')).toBe('刷新令牌有效期（天）');
    expect(translateRuntimeConfigText('Token 有效期参数')).toBe('令牌有效期参数');
  });

  it('adds days unit to translated day fields', () => {
    expect(hasDaysUnit('访问令牌有效期（天）')).toBe(true);
    expect(formatRuntimeConfigDefault('访问令牌有效期（天）', 1)).toBe('默认：1 天');
    expect(formatRuntimeConfigDefault('通信超时（秒）', 30)).toBe('默认：30');
  });

  it('translates model names inside runtime config messages', () => {
    expect(translateRuntimeConfigText('SwitchData: 成功，候选 4 条')).toBe('开关量数据：成功，候选 4 条');
  });
});
