export const languageNames = {
  kk: "Қазақша", ru: "Русский", en: "English", tr: "Türkçe",
  uz: "O‘zbekcha", ky: "Кыргызча", de: "Deutsch", es: "Español"
} as const;

export type Language = keyof typeof languageNames;
type Texts = { welcome: string; menu: string; help: string; choose: string; changed: string; error: string };
export const translations: Record<Language, Texts> = {
  kk: {welcome:"Сәлем! VPN қызметінің ботына қош келдіңіз.", menu:"🌐 Тіл", help:"/start — басты мәзір\n/help — анықтама\n/language — тілді таңдау\nVPN және жазылымдар әзірленіп жатыр.", choose:"Тілді таңдаңыз:", changed:"Тіл сақталды.", error:"Баптауларды сақтау немесе жүктеу мүмкін болмады. Кейінірек қайталап көріңіз."},
  ru: {welcome:"Привет! Добро пожаловать в бот будущего VPN-сервиса.", menu:"🌐 Язык", help:"/start — главное меню\n/help — справка\n/language — выбор языка\nVPN и подписки находятся в разработке.", choose:"Выберите язык:", changed:"Язык сохранён.", error:"Не удалось загрузить или сохранить настройки. Попробуйте позже."},
  en: {welcome:"Hello! Welcome to the future VPN service bot.", menu:"🌐 Language", help:"/start — main menu\n/help — help\n/language — choose a language\nVPN and subscriptions are in development.", choose:"Choose a language:", changed:"Language saved.", error:"Could not load or save settings. Please try again later."},
  tr: {welcome:"Merhaba! Gelecekteki VPN hizmetinin botuna hoş geldiniz.", menu:"🌐 Dil", help:"/start — ana menü\n/help — yardım\n/language — dil seçimi\nVPN ve abonelikler geliştiriliyor.", choose:"Bir dil seçin:", changed:"Dil kaydedildi.", error:"Ayarlar yüklenemedi veya kaydedilemedi. Lütfen daha sonra tekrar deneyin."},
  uz: {welcome:"Salom! Kelajakdagi VPN xizmati botiga xush kelibsiz.", menu:"🌐 Til", help:"/start — bosh menyu\n/help — yordam\n/language — tilni tanlash\nVPN va obunalar ishlab chiqilmoqda.", choose:"Tilni tanlang:", changed:"Til saqlandi.", error:"Sozlamalarni yuklash yoki saqlash mumkin bo‘lmadi. Keyinroq qayta urinib ko‘ring."},
  ky: {welcome:"Салам! Келечектеги VPN кызматынын ботуна кош келиңиз.", menu:"🌐 Тил", help:"/start — башкы меню\n/help — жардам\n/language — тил тандоо\nVPN жана жазылуулар иштелип жатат.", choose:"Тилди тандаңыз:", changed:"Тил сакталды.", error:"Жөндөөлөрдү жүктөө же сактоо мүмкүн болгон жок. Кийинчерээк кайра аракет кылыңыз."},
  de: {welcome:"Hallo! Willkommen beim Bot des zukünftigen VPN-Dienstes.", menu:"🌐 Sprache", help:"/start — Hauptmenü\n/help — Hilfe\n/language — Sprache wählen\nVPN und Abonnements sind in Entwicklung.", choose:"Wählen Sie eine Sprache:", changed:"Sprache gespeichert.", error:"Einstellungen konnten nicht geladen oder gespeichert werden. Bitte versuchen Sie es später erneut."},
  es: {welcome:"¡Hola! Te damos la bienvenida al bot del futuro servicio VPN.", menu:"🌐 Idioma", help:"/start — menú principal\n/help — ayuda\n/language — elegir idioma\nLa VPN y las suscripciones están en desarrollo.", choose:"Elige un idioma:", changed:"Idioma guardado.", error:"No se pudieron cargar o guardar los ajustes. Inténtalo de nuevo más tarde."}
};

export function isLanguage(value: string): value is Language {
  return Object.prototype.hasOwnProperty.call(languageNames, value);
}
export function initialLanguage(value?: string): Language {
  const code = (value || "").toLowerCase().split(/[-_]/)[0];
  return isLanguage(code) ? code : "ru";
}
