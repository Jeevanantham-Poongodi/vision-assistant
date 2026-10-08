/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_WS_BASE?: string;
  readonly VITE_USE_MOCKS?: string;
  readonly VITE_DEMO_USER_ID?: string;
  readonly VITE_DEMO_GUARDIAN_ID?: string;
  readonly VITE_MAPBOX_TOKEN?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
