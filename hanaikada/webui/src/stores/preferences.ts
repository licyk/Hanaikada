import { defineStore } from 'pinia';
import { reactive, watch } from 'vue';
import { getClientState, putClientState } from '@/api/queries/app';
import type { ListSort } from '@/api/types';
import type { ThemeMode } from '@/theme/applyTheme';
import { DEFAULT_SOURCE_COLOR } from '@/theme/scheme';

export type Locale = 'en' | 'zh-CN' | 'ja';
/** A locale, or ``auto`` to follow the system's language. */
export type LocalePreference = Locale | 'auto';
const LOCALE_PREFERENCES: LocalePreference[] = ['auto', 'en', 'zh-CN', 'ja'];
export type InfoTab = 'parameters' | 'prompt' | 'raw' | 'info';
export type ShortcutAction = 'favorite' | 'delete' | 'download' | 'copyPrompt' | 'toggleInfo' | 'next' | 'previous' | 'slideshow';

export const DEFAULT_SHORTCUTS: Record<ShortcutAction, string> = {
  favorite: 'f',
  delete: 'Delete',
  download: 'd',
  copyPrompt: 'c',
  toggleInfo: 'i',
  next: 'ArrowRight',
  previous: 'ArrowLeft',
  slideshow: 's',
};

export interface Preferences {
  theme: ThemeMode;
  sourceColor: string;
  contrast: number;
  locale: LocalePreference;
  lastRoot: string | null;
  cellSize: number;
  showNames: boolean;
  /** Videos play, muted and looping, in their grid cells; off, a still frame is shown. */
  videoAutoplay: boolean;
  sort: ListSort;
  desc: boolean;
  infoOpen: boolean;
  infoWidth: number;
  infoTab: InfoTab;
  slideshowSeconds: number;
  shortcuts: Record<ShortcutAction, string>;
}

const STORAGE_KEY = 'hanaikada:preferences';
const SERVER_KEY = 'preferences';

export const DEFAULTS: Preferences = {
  theme: 'system',
  sourceColor: DEFAULT_SOURCE_COLOR,
  contrast: 0,
  locale: 'auto',
  lastRoot: null,
  cellSize: 200,
  showNames: true,
  videoAutoplay: true,
  sort: 'mtime',
  desc: true,
  infoOpen: true,
  infoWidth: 420,
  infoTab: 'parameters',
  slideshowSeconds: 4,
  shortcuts: { ...DEFAULT_SHORTCUTS },
};

function readLocal(): Partial<Preferences> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
  } catch {
    return {};
  }
}

function merge(base: Preferences, patch: Partial<Preferences>): Preferences {
  const merged = { ...base, ...patch, shortcuts: { ...base.shortcuts, ...(patch.shortcuts ?? {}) } };
  // A locale this build does not know (saved by a newer one, or edited by hand) follows the system.
  if (!LOCALE_PREFERENCES.includes(merged.locale)) merged.locale = 'auto';
  return merged;
}

/**
 * Interface preferences are client state. They persist to the server's client-state endpoint, so
 * they follow the user across browsers, with a localStorage copy so index.html can apply the theme
 * before the bundle loads.
 */
export const usePreferencesStore = defineStore('preferences', () => {
  const prefs = reactive<Preferences>(merge(DEFAULTS, readLocal()));
  let serverTimer: ReturnType<typeof setTimeout> | undefined;
  let loaded = false;

  watch(
    prefs,
    (value) => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
      } catch {
        /* private mode */
      }
      if (!loaded) return;
      clearTimeout(serverTimer);
      serverTimer = setTimeout(() => putClientState(SERVER_KEY, { ...value }).catch(() => undefined), 500);
    },
    { deep: true },
  );

  async function loadFromServer() {
    try {
      const remote = await getClientState<Partial<Preferences>>(SERVER_KEY);
      if (remote && typeof remote === 'object') Object.assign(prefs, merge(prefs, remote));
    } catch {
      /* offline or needs a token: keep local values */
    }
    loaded = true;
  }

  return { prefs, loadFromServer };
});
