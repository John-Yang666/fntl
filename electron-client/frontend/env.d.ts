/// <reference types="vite/client" />

interface BtNmsClientConfig {
  btBaseUrl: string;
  syBaseUrl: string;
}

interface BtNmsClientBridge {
  getConfig(): Promise<BtNmsClientConfig | null>;
  saveConfig(config: BtNmsClientConfig): Promise<void>;
  openSettings(): Promise<void>;
  openBackendAdmin(system: 'bt' | 'sy', path: string): Promise<void>;
}

interface Window {
  btNmsClient?: BtNmsClientBridge;
}
