/* ---------------- types ---------------- */
import type { Board, DeviceStatus, RelayStatus } from './types';

/* ---------- 小工具 ---------- */
const bit  = (byte: string, idx: number) => byte[7 - idx] ?? '0';
const bits = (byte: string, [h, l]: [number, number]) => bit(byte, h) + bit(byte, l);
const byteAt = (bin: string, charIdx: number) => {
  const start = (charIdx - 4) * 8;
  return start >= 0 && start + 8 <= bin.length
    ? bin.slice(start, start + 8)
    : null;
};

/* ---------- 结果骨架 ---------- */
const blankMain  = (): DeviceStatus => ({
  Status1:'null', Status2:'null',
  Status3:'null', Status4:'null',
  Status5:'null', Status52:'null',
  Status6:'null', Status7:'null',
  Status72:'null', Status8:'null',
});
const blankRelay = (): RelayStatus => ({
  Status1:'null', Status2:'null',
  Status3:'null', Status4:'null',
  Status5:'null', Status6:'null',
  Status7:'null', Status8:'null',
});
const blankBoards = (): Board[] => [
  { name:'电源板A', status:'null' },
  { name:'通信板A', status:'null' },
  { name:'通信板B', status:'null' },
  { name:'CPU板A',  status:'null' },
  { name:'CPU板B',  status:'null' },
  { name:'电源板B', status:'null' },
];

export interface ParsedSwitchStatus {
  boards1: Board[]; boards2: Board[];
  direction1MainStatus:  DeviceStatus[];
  direction1RelayStatusA: RelayStatus[];
  direction1RelayStatusB: RelayStatus[];
  direction2MainStatus:  DeviceStatus[];
  direction2RelayStatusA: RelayStatus[];
  direction2RelayStatusB: RelayStatus[];
}

/* ------------------------------------------------------------------ */
/*                       声明式解析描述表                              */
/* ------------------------------------------------------------------ */
type TargetKey = keyof ParsedSwitchStatus;

interface Desc<T> {
  target : TargetKey;
  idx?   : number;                     // 目标数组下标，默认 0
  field  : keyof T;                    // 哪个字段
  char   : number;                     // 协议字节序号
  bitPos : number | [number,number];   // 位或位组合
  map    : (raw: string, code?: string)=>string;
}

/* ------ 1. 板卡 & 电源板状态 ------ */
const boardDescs: Array<Desc<Board>> = [
  // 一方向 电源板 A/B
  { target:'boards1', idx:0, field:'status', char:4, bitPos:0, map: b=>b==='0'?'正常':'故障' },
  { target:'boards1', idx:5, field:'status', char:4, bitPos:1, map: b=>b==='0'?'正常':'故障' },
  // 二方向 电源板 A/B
  { target:'boards2', idx:0, field:'status', char:4, bitPos:2, map: b=>b==='0'?'正常':'故障' },
  { target:'boards2', idx:5, field:'status', char:4, bitPos:3, map: b=>b==='0'?'正常':'故障' },
];

/* ------ 2. CPU 板 A/B 主备 ------ */
const cpuStatus = (code:string) =>
  ({ '1010':'主用','0101':'备用','1001':'故障' } as const)[code] ?? '正常';

const cpuDescs: Array<Desc<Board>> = [
  { target:'boards1', idx:3, field:'status', char:19, bitPos:[3,2], map:(r,c)=>cpuStatus(c!) },
  { target:'boards1', idx:4, field:'status', char:28, bitPos:[3,2], map:(r,c)=>cpuStatus(c!) },
  { target:'boards2', idx:3, field:'status', char:37, bitPos:[3,2], map:(r,c)=>cpuStatus(c!) },
  { target:'boards2', idx:4, field:'status', char:46, bitPos:[3,2], map:(r,c)=>cpuStatus(c!) },
];

/* ------ 3. 通信板 & 站间通道（由主用 CPU 决定） ------ */
const commDescs: Array<Desc<any>> = [
  // 一方向 通信板 A/B & Status1/2
  { target:'boards1', idx:1, field:'status', char:16, bitPos:2, map:b=>b==='0'?'正常':'故障' },
  { target:'boards1', idx:1, field:'status', char:25, bitPos:2, map:b=>b==='0'?'正常':'故障' },

  { target:'boards1', idx:2, field:'status', char:16, bitPos:4, map:b=>b==='0'?'正常':'故障' },
  { target:'boards1', idx:2, field:'status', char:25, bitPos:4, map:b=>b==='0'?'正常':'故障' },

  { target:'direction1MainStatus', field:'Status1', char:16, bitPos:2, map:b=>b==='0'?'正常':'故障' },
  { target:'direction1MainStatus', field:'Status1', char:25, bitPos:2, map:b=>b==='0'?'正常':'故障' },

  { target:'direction1MainStatus', field:'Status2', char:16, bitPos:4, map:b=>b==='0'?'正常':'故障' },
  { target:'direction1MainStatus', field:'Status2', char:25, bitPos:4, map:b=>b==='0'?'正常':'故障' },

  // 二方向 同理
  { target:'boards2', idx:1, field:'status', char:34, bitPos:2, map:b=>b==='0'?'正常':'故障' },
  { target:'boards2', idx:1, field:'status', char:43, bitPos:2, map:b=>b==='0'?'正常':'故障' },

  { target:'boards2', idx:2, field:'status', char:34, bitPos:4, map:b=>b==='0'?'正常':'故障' },
  { target:'boards2', idx:2, field:'status', char:43, bitPos:4, map:b=>b==='0'?'正常':'故障' },

  { target:'direction2MainStatus', field:'Status1', char:34, bitPos:2, map:b=>b==='0'?'正常':'故障' },
  { target:'direction2MainStatus', field:'Status1', char:43, bitPos:2, map:b=>b==='0'?'正常':'故障' },

  { target:'direction2MainStatus', field:'Status2', char:34, bitPos:4, map:b=>b==='0'?'正常':'故障' },
  { target:'direction2MainStatus', field:'Status2', char:43, bitPos:4, map:b=>b==='0'?'正常':'故障' },
];

/* ------ 4. 主要状态：QHJ/切换 & CPU 通信 ------ */
const modeMap = { '00':'无效','01':'强制电缆','10':'自动','11':'强制光缆' } as const;

const mainDescs: Array<Desc<DeviceStatus>> = [
  // —— CPU 通信（补回原来 4 号字节的 Status3/4）——
  { target:'direction1MainStatus', field:'Status3', char:4, bitPos:4, map:b=>b==='0'?'正常':'故障' },
  { target:'direction1MainStatus', field:'Status4', char:4, bitPos:5, map:b=>b==='0'?'正常':'故障' },
  { target:'direction2MainStatus', field:'Status3', char:4, bitPos:6, map:b=>b==='0'?'正常':'故障' },
  { target:'direction2MainStatus', field:'Status4', char:4, bitPos:7, map:b=>b==='0'?'正常':'故障' },

  // —— 一方向 QHJ / 切换 —— 
  { target:'direction1MainStatus', field:'Status5',  char:7,  bitPos:0, map:b=>b==='0'?'落下(电缆)':'吸起(光缆)' },
  { target:'direction1MainStatus', field:'Status52', char:7,  bitPos:1, map:b=>b==='0'?'正常':'故障' },
  { target:'direction1MainStatus', field:'Status6',  char:7,  bitPos:[3,2], map:m=>modeMap[m as keyof typeof modeMap] },

  { target:'direction1MainStatus', field:'Status7',  char:9,  bitPos:0, map:b=>b==='0'?'落下(电缆)':'吸起(光缆)' },
  { target:'direction1MainStatus', field:'Status72', char:9,  bitPos:1, map:b=>b==='0'?'正常':'故障' },
  { target:'direction1MainStatus', field:'Status8',  char:9,  bitPos:[3,2], map:m=>modeMap[m as keyof typeof modeMap] },

  // —— 二方向 同理 —— 
  { target:'direction2MainStatus', field:'Status5',  char:11, bitPos:0, map:b=>b==='0'?'落下(电缆)':'吸起(光缆)' },
  { target:'direction2MainStatus', field:'Status52', char:11, bitPos:1, map:b=>b==='0'?'正常':'故障' },
  { target:'direction2MainStatus', field:'Status6',  char:11, bitPos:[3,2], map:m=>modeMap[m as keyof typeof modeMap] },

  { target:'direction2MainStatus', field:'Status7',  char:13, bitPos:0, map:b=>b==='0'?'落下(电缆)':'吸起(光缆)' },
  { target:'direction2MainStatus', field:'Status72', char:13, bitPos:1, map:b=>b==='0'?'正常':'故障' },
  { target:'direction2MainStatus', field:'Status8',  char:13, bitPos:[3,2], map:m=>modeMap[m as keyof typeof modeMap] },
];

/* ------ 5. 继电器 —— 保持不变 ------ */
const relayMap = (b:string)=>b==='0'?'落下':'吸起';
const relayDescs: Array<Desc<RelayStatus>> = [
  { target:'direction1RelayStatusA', field:'Status1', char:14, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status2', char:14, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status3', char:14, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status4', char:14, bitPos:6, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status5', char:22, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status6', char:22, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status7', char:22, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status8', char:22, bitPos:6, map:relayMap },

  { target:'direction1RelayStatusB', field:'Status1', char:23, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status2', char:23, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status3', char:23, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status4', char:23, bitPos:6, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status5', char:31, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status6', char:31, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status7', char:31, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status8', char:31, bitPos:6, map:relayMap },

  { target:'direction2RelayStatusA', field:'Status1', char:32, bitPos:0, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status2', char:32, bitPos:2, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status3', char:32, bitPos:4, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status4', char:32, bitPos:6, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status5', char:40, bitPos:0, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status6', char:40, bitPos:2, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status7', char:40, bitPos:4, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status8', char:40, bitPos:6, map:relayMap },

  { target:'direction2RelayStatusB', field:'Status1', char:41, bitPos:0, map:relayMap },
  { target:'direction2RelayStatusB', field:'Status2', char:41, bitPos:2, map:relayMap },
  { target:'direction2RelayStatusB', field:'Status3', char:41, bitPos:4, map:relayMap },
  { target:'direction2RelayStatusB', field:'Status4', char:41, bitPos:6, map:relayMap },
  { target:'direction2RelayStatusB', field:'Status5', char:49, bitPos:0, map:relayMap },
  { target:'direction2RelayStatusB', field:'Status6', char:49, bitPos:2, map:relayMap },
  { target:'direction2RelayStatusB', field:'Status7', char:49, bitPos:4, map:relayMap },
  { target:'direction2RelayStatusB', field:'Status8', char:49, bitPos:6, map:relayMap },
];

/* ------------------------------------------------------------------ */
/*                             主函数                                 */
/* ------------------------------------------------------------------ */
export function parseSwitchStatus(binary: string): ParsedSwitchStatus {
  const res: ParsedSwitchStatus = {
    boards1: blankBoards(),
    boards2: blankBoards(),
    direction1MainStatus  : [blankMain()],
    direction1RelayStatusA: [blankRelay()],
    direction1RelayStatusB: [blankRelay()],
    direction2MainStatus  : [blankMain()],
    direction2RelayStatusA: [blankRelay()],
    direction2RelayStatusB: [blankRelay()],
  };

  type AnyDesc = Desc<any>;
  const apply = (d: AnyDesc) => {
    const b = byteAt(binary, d.char);
    if (!b) return;
    const raw = Array.isArray(d.bitPos)
      ? bits(b, d.bitPos as [number,number])
      : bit(b, d.bitPos as number);

    const arr = (res as any)[d.target] as any[];
    const obj = Array.isArray(arr) ? arr[d.idx ?? 0] : arr;
    const key = d.field as string;

    obj[key] = d.map(raw, raw);
  };

  ;[...boardDescs, ...cpuDescs, ...commDescs, ...mainDescs, ...relayDescs].forEach(apply);
  return res;
}
