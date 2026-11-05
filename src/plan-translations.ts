import { Language } from "./translations";

type PlanTexts = { button: string; list: string; days: string; duration: string; notice: string; back: string; home: string; homeMessage: string; busy: string };
export const planTranslations: Record<Language, PlanTexts> = {
  kk: {button:"💎 Тарифтер", list:"Болашақ тарифті таңдаңыз. Бағалар мен төлем кейінірек пайда болады.", days:"күн", duration:"Мерзімі", notice:"Бұл таныстыру тарифі. Төлем мен VPN қосылымы кейінірек пайда болады.", back:"← Тарифтерге оралу", home:"🏠 Басты мәзір", homeMessage:"Басты мәзір.", busy:"Алдымен ағымдағы хабарламаны аяқтаңыз немесе болдырмаңыз."},
  ru: {button:"💎 Тарифы", list:"Выберите будущий тариф. Цены и оплата появятся позже.", days:"дней", duration:"Срок", notice:"Это ознакомительный тариф. Оплата и подключение VPN появятся позже.", back:"← К списку тарифов", home:"🏠 Главное меню", homeMessage:"Главное меню.", busy:"Сначала завершите или отмените текущее сообщение."},
  en: {button:"💎 Plans", list:"Choose a future plan. Prices and payment will be available later.", days:"days", duration:"Duration", notice:"This is an informational plan. Payment and VPN connection will be available later.", back:"← Back to plans", home:"🏠 Main menu", homeMessage:"Main menu.", busy:"Please finish or cancel your current message first."},
  tr: {button:"💎 Tarifeler", list:"Gelecekteki bir tarifeyi seçin. Fiyatlar ve ödeme daha sonra sunulacak.", days:"gün", duration:"Süre", notice:"Bu, tanıtım amaçlı bir tarifedir. Ödeme ve VPN bağlantısı daha sonra sunulacak.", back:"← Tarifelere dön", home:"🏠 Ana menü", homeMessage:"Ana menü.", busy:"Önce mevcut mesajınızı tamamlayın veya iptal edin."},
  uz: {button:"💎 Tariflar", list:"Kelajakdagi tarifni tanlang. Narxlar va to‘lov keyinroq paydo bo‘ladi.", days:"kun", duration:"Muddati", notice:"Bu tanishtiruv tarifi. To‘lov va VPN ulanishi keyinroq paydo bo‘ladi.", back:"← Tariflarga qaytish", home:"🏠 Bosh menyu", homeMessage:"Bosh menyu.", busy:"Avval joriy xabarni yakunlang yoki bekor qiling."},
  ky: {button:"💎 Тарифтер", list:"Келечектеги тарифти тандаңыз. Баалар жана төлөм кийинчерээк кошулат.", days:"күн", duration:"Мөөнөтү", notice:"Бул тааныштыруу тарифи. Төлөм жана VPN туташуу кийинчерээк кошулат.", back:"← Тарифтерге кайтуу", home:"🏠 Башкы меню", homeMessage:"Башкы меню.", busy:"Адегенде учурдагы билдирүүнү бүтүрүңүз же жокко чыгарыңыз."},
  de: {button:"💎 Tarife", list:"Wählen Sie einen zukünftigen Tarif. Preise und Zahlung folgen später.", days:"Tage", duration:"Laufzeit", notice:"Dies ist ein Tarif zur Information. Zahlung und VPN-Verbindung folgen später.", back:"← Zur Tarifübersicht", home:"🏠 Hauptmenü", homeMessage:"Hauptmenü.", busy:"Bitte schließen Sie Ihre aktuelle Nachricht zuerst ab oder brechen Sie sie ab."},
  es: {button:"💎 Tarifas", list:"Elige una tarifa futura. Los precios y el pago llegarán más adelante.", days:"días", duration:"Duración", notice:"Esta es una tarifa informativa. El pago y la conexión VPN llegarán más adelante.", back:"← Volver a tarifas", home:"🏠 Menú principal", homeMessage:"Menú principal.", busy:"Primero termina o cancela tu mensaje actual."}
};

const futurePayment: Record<Language, { list: string; notice: string }> = {
  ru: { list: 'Выберите тариф. Оплата пока недоступна.', notice: 'Оплата пока недоступна.' },
  en: { list: 'Choose a plan. Payment is not available yet.', notice: 'Payment is not available yet.' },
  kk: { list: 'Тарифті таңдаңыз. Төлем әзірге қолжетімсіз.', notice: 'Төлем әзірге қолжетімсіз.' },
  tr: { list: 'Bir tarife seçin. Ödeme henüz kullanılamıyor.', notice: 'Ödeme henüz kullanılamıyor.' },
  uz: { list: 'Tarifni tanlang. To‘lov hali mavjud emas.', notice: 'To‘lov hali mavjud emas.' },
  ky: { list: 'Тарифти тандаңыз. Төлөм азырынча жеткиликсиз.', notice: 'Төлөм азырынча жеткиликсиз.' },
  de: { list: 'Wählen Sie einen Tarif. Die Zahlung ist noch nicht verfügbar.', notice: 'Die Zahlung ist noch nicht verfügbar.' },
  es: { list: 'Elige una tarifa. El pago aún no está disponible.', notice: 'El pago aún no está disponible.' }
};
for (const language of Object.keys(futurePayment) as Language[]) {
  Object.assign(planTranslations[language], futurePayment[language]);
}
