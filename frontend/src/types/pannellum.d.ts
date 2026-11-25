export interface PannellumHotspotConfig {
  id?: string;
  pitch: number;
  yaw: number;
  type?: string;
  text?: string;
  cssClass?: string;
  createTooltipFunc?: (hotSpotDiv: HTMLElement, args: unknown) => void;
  createTooltipArgs?: unknown;
  clickHandlerFunc?: (event: MouseEvent, args: unknown) => void;
  clickHandlerArgs?: unknown;
}

export interface PannellumViewerOptions {
  type: "equirectangular" | "cubemap" | "multires";
  panorama: string;
  autoLoad?: boolean;
  showControls?: boolean;
  compass?: boolean;
  hfov?: number;
  minHfov?: number;
  maxHfov?: number;
  hotSpots?: PannellumHotspotConfig[];
}

export interface PannellumViewerInstance {
  on: (eventName: string, listener: (...args: unknown[]) => void) => void;
  destroy: () => void;
}

declare global {
  interface Window {
    pannellum?: {
      viewer: (
        container: HTMLElement | string,
        config: PannellumViewerOptions
      ) => PannellumViewerInstance;
    };
  }
}

export {};
