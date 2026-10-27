import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN.ts'
import ruRU from './locales/ru-RU.ts'
import enUS from './locales/en-US.ts'
import koKR from './locales/ko-KR.ts'

const messages = {
  'zh-CN': zhCN,
  'en-US': enUS,
  'ru-RU': ruRU,
  'ko-KR': koKR
}

// UI 语言白名单：只有列在这里的语言才会出现在语言选择器中。
// 其余语言包仍然加载，用户已保存的旧偏好不会因此报错；要放开某个语言，加回数组即可。
export const ENABLED_UI_LOCALES: readonly string[] = ['zh-CN']

// Получаем сохраненный язык из localStorage или используем китайский по умолчанию
const savedLocale = localStorage.getItem('locale') || 'zh-CN'
// 某个语言被移出白名单后，仍持有旧偏好的用户会卡在一个选不回来的界面语言里，
// 这里在启动时收敛回第一个可用语言。
const initialLocale = ENABLED_UI_LOCALES.includes(savedLocale) ? savedLocale : ENABLED_UI_LOCALES[0]

const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: 'zh-CN',
  globalInjection: true,
  // Some translations intentionally embed `<strong>` markup (e.g. agent step summaries).
  // We render them via v-html with our own sanitization, so silence vue-i18n's HTML warning
  // to avoid flooding the console and slowing renders during history loads.
  warnHtmlMessage: false,
  messages
})

export default i18n