export interface Board {
  name: string;
  status: '备用' | '主用' | '正常' | '故障' | 'null';
}

export interface DeviceStatus {
  Status1: string;  Status2: string;  Status3: string;  Status4: string;
  Status5: string;  Status52: string; Status6: string;
  Status7: string;  Status72: string; Status8: string;
}

export interface RelayStatus {
  Status1: string; Status2: string; Status3: string; Status4: string;
  Status5: string; Status6: string; Status7: string; Status8: string;
}

export interface ParsedSwitchStatus {
  boards1: Board[];
  boards2: Board[];
  direction1MainStatus: DeviceStatus[];
  direction1RelayStatusA: RelayStatus[];
  direction1RelayStatusB: RelayStatus[];
  direction2MainStatus: DeviceStatus[];
  direction2RelayStatusA: RelayStatus[];
  direction2RelayStatusB: RelayStatus[];
}
