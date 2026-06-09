export type SystemType = 'bt' | 'sy';

export type FaultState = 'normal' | 'offline' | 'direction1_fault' | 'direction2_fault' | 'alarm';

export interface DemoDevice {
  system: SystemType;
  device_id: number;
  name: string;
  depot: string;
  line: string;
  ip_address: string;
  x_coordinate: number;
  y_coordinate: number;
  direction1_neighbor_id: number | null;
  direction1_neighbor_direction: number | null;
  direction2_neighbor_id: number | null;
  direction2_neighbor_direction: number | null;
  direction3_neighbor_id?: number | null;
  direction3_neighbor_direction?: number | null;
  remark: string;
  fault: FaultState;
  analogFault?: boolean;
  syRunState?: 'normal' | 'started' | 'main_disabled' | 'backup_disabled';
}

export interface AlertRecord {
  id: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;
  timestamp_end: string | null;
  is_confirmed: boolean;
  confirmed?: boolean;
  duration_seconds: number;
}

export interface RelayActionRecord {
  id: string;
  device: number;
  device_id: number;
  device_name: string;
  relay: string;
  action: string;
  source: string;
  timestamp: string;
}

export interface UserOperationRecord {
  id: string;
  device: number | null;
  device_id: number | null;
  device_name: string | null;
  function_code: string;
  operation: string;
  username: string | null;
  timestamp: string;
}

export interface SwitchDataRecord {
  id: string;
  device: number;
  device_id: number;
  device_name: string;
  switch_status_text: string;
  switch_status_hex: string;
  version?: string;
  timestamp: string;
}

export interface AnalogDataRecord {
  id: string;
  device: number;
  device_id: number;
  device_name: string;
  voltage_1: number;
  current_1: number;
  voltage_2: number;
  current_2: number;
  timestamp: string;
}

export interface SystemRecords {
  alerts: AlertRecord[];
  relayActions: RelayActionRecord[];
  userOperations: UserOperationRecord[];
  switchData: SwitchDataRecord[];
  analogData: AnalogDataRecord[];
}

export interface SimulatorState {
  devices: Record<SystemType, DemoDevice[]>;
  records: Record<SystemType, SystemRecords>;
}

export interface DeviceStateUpdate {
  system: SystemType;
  deviceId: number;
  fault?: FaultState;
  analogFault?: boolean;
  syRunState?: DemoDevice['syRunState'];
}
