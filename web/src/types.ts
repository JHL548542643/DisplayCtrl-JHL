export type Luminance = {
  current: number;
  maximum: number;
  vcp: string;
};

export type LuminanceCapability = {
  vcp: string;
  readable: boolean;
  writable: boolean;
  current: number | null;
  maximum: number | null;
};

export type ContrastCapability = {
  vcp: string;
  declared: boolean;
  readable: boolean;
  writable: boolean;
  current: number | null;
  maximum: number | null;
};

export type VolumeCapability = {
  vcp: string;
  declared: boolean;
  readable: boolean;
  writable: boolean;
  current: number | null;
  maximum: number | null;
};

export type InputSourceCapability = {
  vcp: string;
  declared: boolean;
  readable: boolean;
  writable: boolean;
  current: number | null;
  maximum: number | null;
};

export type PowerModeCapability = {
  vcp: string;
  declared: boolean;
  readable: boolean;
  writable: boolean;
  current: number | null;
  maximum: number | null;
};

export type RgbChannelCapability = {
  vcp: string;
  declared: boolean;
  readable: boolean;
  writable: boolean;
  current: number | null;
  maximum: number | null;
};

export type RgbGainsCapability = {
  declared: boolean;
  readable: boolean;
  writable: boolean;
  red: RgbChannelCapability;
  green: RgbChannelCapability;
  blue: RgbChannelCapability;
};

export type Capabilities = {
  luminance: LuminanceCapability;
  contrast: ContrastCapability | null;
  volume: VolumeCapability | null;
  rgb_gains: RgbGainsCapability | null;
  input_source: InputSourceCapability | null;
  power_mode: PowerModeCapability | null;
};

export type Monitor = {
  id: string;
  stable: boolean;
  identity_quality: string;
  writable: boolean;
  failure: string | null;
  message: string | null;
  model: string | null;
  manufacturer: string | null;
  product_code: string | null;
  serial: string | null;
  description: string;
  device: string;
  primary: boolean;
  session_index: number;
  rect: number[];
  luminance: Luminance | null;
  capabilities: Capabilities;
  winerr: number | null;
};

export type Health = {
  ok: boolean;
  service: string;
  version: string;
  platform: string;
  backend: string;
  demo: boolean;
  loopback_only: boolean;
  policy: {
    vcp: string[];
    luminance_min: number;
    luminance_max: number;
    required_maximum: number;
    min_interval_s: number;
    max_writes_per_minute: number;
    verify_reads: number;
    verify_settle_s: number;
  };
};

export type SetResult = {
  monitor_id: string;
  requested: number;
  previous: number;
  verified: number;
  noop: boolean;
  rolled_back: boolean;
};

export type ApiErrorBody = {
  kind: string;
  message: string;
  retryable: boolean;
};
