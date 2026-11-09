/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" serves the API from MSW mocks instead of the real relative /api. */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
