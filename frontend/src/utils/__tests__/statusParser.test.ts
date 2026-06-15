import { describe, expect, it } from 'vitest';
import { parseSwitchStatus } from '../statusParser';

const buildBinary = (updates: Array<[number, number, 0 | 1]> = []) => {
  const bytes = Array.from({ length: 46 }, () => Array.from('00000000'));
  for (const [protocolByte, bitPosition, value] of updates) {
    const byteIndex = protocolByte - 4;
    bytes[byteIndex][7 - bitPosition] = String(value);
  }
  return bytes.map((byte) => byte.join('')).join('');
};

describe('BT switch status parser', () => {
  it('decodes board faults, switch mode and relay states from protocol bits', () => {
    const parsed = parseSwitchStatus(
      buildBinary([
        [4, 0, 1],
        [7, 0, 1],
        [7, 3, 1],
        [14, 0, 1],
      ]),
    );

    expect(parsed.boards1[0]).toEqual({ name: '电源板A', status: '故障' });
    expect(parsed.direction1MainStatus[0].Status5).toBe('吸起(光缆)');
    expect(parsed.direction1MainStatus[0].Status6).toBe('自动');
    expect(parsed.direction1RelayStatusA[0].Status1).toBe('吸起');
  });

  it('leaves missing protocol bytes as null status fields', () => {
    const parsed = parseSwitchStatus('00000000');

    expect(parsed.boards1[0].status).toBe('正常');
    expect(parsed.direction1MainStatus[0].Status5).toBe('null');
    expect(parsed.direction2RelayStatusB[0].Status8).toBe('null');
  });
});
