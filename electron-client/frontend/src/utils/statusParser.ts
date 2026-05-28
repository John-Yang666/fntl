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
  char   : number;                     // 协议字节序号（协议里的“第 char 个字节”）
  bitPos : number | [number,number] | [number,number,number,number];   // 位或位组合
  map    : (raw: string, code?: string)=>string;
}

/* ------ 1. 板卡 & 电源板状态 ------ */
const boardDescs: Array<Desc<Board>> = [
  // 一方向 电源板 A/B（char:4 的 0/1 位）
  { target:'boards1', idx:0, field:'status', char:4, bitPos:0, map: b=>b==='0'?'正常':'故障' },
  { target:'boards1', idx:5, field:'status', char:4, bitPos:1, map: b=>b==='0'?'正常':'故障' },
  // 二方向 电源板 A/B（char:4 的 2/3 位）
  { target:'boards2', idx:0, field:'status', char:4, bitPos:2, map: b=>b==='0'?'正常':'故障' },
  { target:'boards2', idx:5, field:'status', char:4, bitPos:3, map: b=>b==='0'?'正常':'故障' },
];

/* ------ 2. CPU 板 A/B 主备 ------ */
const cpuStatus = (code:string) =>
  ({ '1010':'主用','0101':'备用','1001':'故障','0000':'异常' } as const)[code] ?? '正常';

const cpuDescs: Array<Desc<Board>> = [
  // 一方向 CPU A/B 的4位码分别在 char:19 / char:28 的低4位（按 [3,2,1,0] 顺序拼接）
  { target:'boards1', idx:3, field:'status', char:19, bitPos:[3,2,1,0], map:(r,c)=>cpuStatus(c!) },
  { target:'boards1', idx:4, field:'status', char:28, bitPos:[3,2,1,0], map:(r,c)=>cpuStatus(c!) },
  // 二方向 CPU A/B 的4位码在 char:37 / char:46
  { target:'boards2', idx:3, field:'status', char:37, bitPos:[3,2,1,0], map:(r,c)=>cpuStatus(c!) },
  { target:'boards2', idx:4, field:'status', char:46, bitPos:[3,2,1,0], map:(r,c)=>cpuStatus(c!) },
];

/* ------ 3. 通信板 & 站间通道（由主用 CPU 决定） ------ */
/** 动态生成“只读主用段”的通信 desc 列表。
 *  一方向：A 主用→读 16；B 主用→读 25；未知→默认 16
 *  二方向：A 主用→读 34；B 主用→读 43；未知→默认 34
 */
function buildCommDescsByMaster(binary: string): Array<Desc<any>> {
  const code4 = (c: number) => {
    const by = byteAt(binary, c);
    return by ? [3,2,1,0].map(i => bit(by, i)).join('') : '';
  };

  // 判主用 CPU
  const d1A = cpuStatus(code4(19));
  const d1B = cpuStatus(code4(28));
  const d2A = cpuStatus(code4(37));
  const d2B = cpuStatus(code4(46));

  const d1Main = d1A === '主用' ? 'A' : d1B === '主用' ? 'B' : 'Unknown';
  const d2Main = d2A === '主用' ? 'A' : d2B === '主用' ? 'B' : 'Unknown';

  const seg1 = d1Main === 'A' ? 16 : d1Main === 'B' ? 25 : 16;
  const seg2 = d2Main === 'A' ? 34 : d2Main === 'B' ? 43 : 34;

  const asOK = (b:string)=>b==='0'?'正常':'故障';

  return [
    // 一方向 通信板A/B & Status1/2 —— 只读 seg1
    { target:'boards1', idx:1, field:'status', char:seg1, bitPos:2, map:asOK },
    { target:'boards1', idx:2, field:'status', char:seg1, bitPos:4, map:asOK },
    { target:'direction1MainStatus', field:'Status1', char:seg1, bitPos:2, map:asOK },
    { target:'direction1MainStatus', field:'Status2', char:seg1, bitPos:4, map:asOK },

    // 二方向 —— 只读 seg2
    { target:'boards2', idx:1, field:'status', char:seg2, bitPos:2, map:asOK },
    { target:'boards2', idx:2, field:'status', char:seg2, bitPos:4, map:asOK },
    { target:'direction2MainStatus', field:'Status1', char:seg2, bitPos:2, map:asOK },
    { target:'direction2MainStatus', field:'Status2', char:seg2, bitPos:4, map:asOK },
  ];
}

/* ------ 4. 主要状态：QHJ/切换 & CPU 通信 ------ */
const modeMap = { '00':'无效','01':'强制电缆','10':'自动','11':'强制光缆' } as const;

const mainDescs: Array<Desc<DeviceStatus>> = [
  // —— CPU 通信（char:4 的 4~7 位）——
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
  // 一方向 A系：本站ZDJ/FDJ/ZXJ/FXJ（char:14），邻站（char:22）
  { target:'direction1RelayStatusA', field:'Status1', char:14, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status2', char:14, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status3', char:14, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status4', char:14, bitPos:6, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status5', char:22, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status6', char:22, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status7', char:22, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusA', field:'Status8', char:22, bitPos:6, map:relayMap },

  // 一方向 B系：本站（char:23），邻站（char:31）
  { target:'direction1RelayStatusB', field:'Status1', char:23, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status2', char:23, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status3', char:23, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status4', char:23, bitPos:6, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status5', char:31, bitPos:0, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status6', char:31, bitPos:2, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status7', char:31, bitPos:4, map:relayMap },
  { target:'direction1RelayStatusB', field:'Status8', char:31, bitPos:6, map:relayMap },

  // 二方向 A系：本站（char:32），邻站（char:40）
  { target:'direction2RelayStatusA', field:'Status1', char:32, bitPos:0, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status2', char:32, bitPos:2, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status3', char:32, bitPos:4, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status4', char:32, bitPos:6, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status5', char:40, bitPos:0, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status6', char:40, bitPos:2, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status7', char:40, bitPos:4, map:relayMap },
  { target:'direction2RelayStatusA', field:'Status8', char:40, bitPos:6, map:relayMap },

  // 二方向 B系：本站（char:41），邻站（char:49）
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
      ? d.bitPos.map(pos => bit(b, pos)).join('')
      : bit(b, d.bitPos as number);

    const arr = (res as any)[d.target] as any[];
    const obj = Array.isArray(arr) ? arr[d.idx ?? 0] : arr;
    const key = d.field as string;

    obj[key] = d.map(raw, raw);
  };

  // 先应用：电源板 + CPU 主备状态（把“主用/备用/故障/异常”写入 boards 列）
  [...boardDescs, ...cpuDescs].forEach(apply);

  // 再应用：根据“主用CPU”只读对应通信段的 desc（替代原先固定的 commDescs）
  const commDescsChosen = buildCommDescsByMaster(binary);
  commDescsChosen.forEach(apply);

  // 最后应用：主要状态 + 继电器
  [...mainDescs, ...relayDescs].forEach(apply);

  return res;
}
