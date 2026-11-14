/// <reference types="vite/client" />

export {};

declare global {
  interface Window {
    desktop?: {
      version: string;
      platform: string;
      revealDataFolder: () => Promise<string | null>;
      openPath: (target: string) => Promise<void>;
      openExternal: (url: string) => Promise<void>;
      chooseDirectory?: () => Promise<string | null>;
    };
  }
}
