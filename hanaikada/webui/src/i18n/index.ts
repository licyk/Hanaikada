import { computed, ref } from 'vue';
import en from '@/i18n/en';
import zhCN from '@/i18n/zh-CN';
import { usePreferencesStore, type Locale, type LocalePreference } from '@/stores/preferences';

type Messages = typeof en;
const MESSAGES: Record<Locale, Messages> = { en, 'zh-CN': zhCN };
export const LOCALES: { value: Locale; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'zh-CN', label: '简体中文' },
];

/** The supported locale for a BCP 47 language tag, or English for one Hanaikada has no translation for. */
export function detectLocale(tag: string | null | undefined): Locale {
  const lower = (tag ?? '').toLowerCase();
  if (lower === 'zh' || lower.startsWith('zh-')) return 'zh-CN';
  return 'en';
}

function systemTag(): string | undefined {
  return typeof navigator === 'undefined' ? undefined : (navigator.languages?.[0] ?? navigator.language);
}

/** The system's language, kept current when it changes while the page is open. */
const systemLocale = ref<Locale>(detectLocale(systemTag()));
if (typeof window !== 'undefined') window.addEventListener('languagechange', () => (systemLocale.value = detectLocale(systemTag())));

/** The locale a preference stands for: ``auto`` follows the system. */
export function resolveLocale(preference: LocalePreference): Locale {
  return preference === 'auto' ? systemLocale.value : preference;
}

function lookup(tree: unknown, key: string): unknown {
  let node: unknown = tree;
  for (const part of key.split('.')) {
    if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) node = (node as Record<string, unknown>)[part];
    else return undefined;
  }
  return node;
}

export function translate(locale: Locale, key: string, params?: Record<string, string | number>): string {
  const found = lookup(MESSAGES[locale], key);
  const fallback = lookup(MESSAGES.en, key);
  const text = typeof found === 'string' ? found : typeof fallback === 'string' ? fallback : key;
  return params ? text.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`)) : text;
}

/** A list-valued message, such as the day names. */
export function translateList(locale: Locale, key: string): string[] {
  const found = lookup(MESSAGES[locale], key) ?? lookup(MESSAGES.en, key);
  return Array.isArray(found) ? found.map(String) : [];
}

/** ``t(key, params)`` in the current locale; reactive to the locale preference and, on ``auto``, to the system's. */
export function useI18n() {
  const store = usePreferencesStore();
  const locale = computed(() => resolveLocale(store.prefs.locale));
  const t = (key: string, params?: Record<string, string | number>) => translate(locale.value, key, params);
  const tl = (key: string) => translateList(locale.value, key);
  /** A platform's name; unknown ones are shown as they are. */
  const platformLabel = (platform: string | null | undefined) => (platform ? translate(locale.value, `platforms.${platform}`).replace(`platforms.${platform}`, platform) : '');
  /** The language choices, led by "Auto detect" naming the language it picked. */
  const localeOptions = computed(() => [
    { value: 'auto', label: t('settings.languageAuto', { language: LOCALES.find((l) => l.value === systemLocale.value)?.label ?? '' }) },
    ...LOCALES,
  ]);
  return { t, tl, locale, localeOptions, platformLabel };
}
