import { Language } from "./translations";
import { Subscription } from "./storage";

type Texts = { button: string; none: string; title: string; active: string; expired: string; start: string; end: string; remaining: string; days: string; hours: string; minutes: string; seconds: string; notice: string; forbidden: string };
export const subscriptionTranslations: Record<Language, Texts> = {
  kk: {button:"👤 Менің жазылымым", none:"Әзірге белсенді жазылымыңыз жоқ.", title:"Сынақ жазылымы", active:"Белсенді", expired:"Мерзімі аяқталған", start:"Басталуы", end:"Аяқталуы", remaining:"Қалған уақыт", days:"күн", hours:"сағ", minutes:"мин", seconds:"сек", notice:"Бұл сынақ жазылымы: төлем жасалмаған және VPN қолжетімділігі берілмейді.", forbidden:"Бұл пәрмен тек әкімшіге қолжетімді."},
  ru: {button:"👤 Моя подписка", none:"У вас пока нет активной подписки.", title:"Тестовая подписка", active:"Активна", expired:"Истекла", start:"Начало", end:"Окончание", remaining:"Осталось", days:"дн.", hours:"ч.", minutes:"мин.", seconds:"сек.", notice:"Это тестовая подписка: оплата не проводилась, VPN-доступ не предоставляется.", forbidden:"Эта команда доступна только администратору."},
  en: {button:"👤 My subscription", none:"You do not have an active subscription yet.", title:"Test subscription", active:"Active", expired:"Expired", start:"Start", end:"End", remaining:"Time left", days:"d", hours:"h", minutes:"min", seconds:"sec", notice:"This is a test subscription: no payment or VPN access is provided.", forbidden:"This command is only available to the administrator."},
  tr: {button:"👤 Aboneliğim", none:"Henüz aktif bir aboneliğiniz yok.", title:"Test aboneliği", active:"Aktif", expired:"Süresi doldu", start:"Başlangıç", end:"Bitiş", remaining:"Kalan süre", days:"gün", hours:"sa", minutes:"dk", seconds:"sn", notice:"Bu bir test aboneliğidir: ödeme yapılmamış ve VPN erişimi sağlanmamıştır.", forbidden:"Bu komut yalnızca yönetici tarafından kullanılabilir."},
  uz: {button:"👤 Mening obunam", none:"Sizda hozircha faol obuna yo‘q.", title:"Sinov obunasi", active:"Faol", expired:"Muddati tugagan", start:"Boshlanishi", end:"Tugashi", remaining:"Qolgan vaqt", days:"kun", hours:"soat", minutes:"daq", seconds:"son", notice:"Bu sinov obunasi: to‘lov qilinmagan va VPN kirishi berilmaydi.", forbidden:"Bu buyruq faqat administrator uchun."},
  ky: {button:"👤 Менин жазылуум", none:"Азырынча активдүү жазылууңуз жок.", title:"Сыноо жазылуусу", active:"Активдүү", expired:"Мөөнөтү бүткөн", start:"Башталышы", end:"Аягы", remaining:"Калган убакыт", days:"күн", hours:"саат", minutes:"мүн", seconds:"сек", notice:"Бул сыноо жазылуусу: төлөм жүргүзүлгөн эмес жана VPN жеткиликтүүлүгү берилбейт.", forbidden:"Бул буйрук администратор үчүн гана."},
  de: {button:"👤 Mein Abonnement", none:"Sie haben noch kein aktives Abonnement.", title:"Testabonnement", active:"Aktiv", expired:"Abgelaufen", start:"Beginn", end:"Ende", remaining:"Verbleibende Zeit", days:"T", hours:"Std.", minutes:"Min.", seconds:"Sek.", notice:"Dies ist ein Testabonnement: Es wurde nichts bezahlt und kein VPN-Zugang bereitgestellt.", forbidden:"Dieser Befehl ist nur für den Administrator verfügbar."},
  es: {button:"👤 Mi suscripción", none:"Todavía no tienes una suscripción activa.", title:"Suscripción de prueba", active:"Activa", expired:"Caducada", start:"Inicio", end:"Fin", remaining:"Tiempo restante", days:"d", hours:"h", minutes:"min", seconds:"s", notice:"Es una suscripción de prueba: no hay pago ni acceso VPN.", forbidden:"Este comando solo está disponible para el administrador."}
};

export function utcDate(seconds: number): string {
  return new Date(seconds * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC");
}

export function describeSubscription(value: Subscription | null, language: Language, nowMs = Date.now()): string {
  const t = subscriptionTranslations[language];
  if (!value) return t.none;
  const remaining = Math.max(0, Math.ceil((value.expires_at * 1000 - nowMs) / 1000));
  const days = Math.floor(remaining / 86400);
  const hours = Math.floor(remaining % 86400 / 3600);
  const minutes = Math.floor(remaining % 3600 / 60);
  const seconds = remaining % 60;
  return `${t.title}\n${remaining > 0 ? t.active : t.expired}\n${t.start}: ${utcDate(value.started_at)}\n${t.end}: ${utcDate(value.expires_at)}\n${t.remaining}: ${days} ${t.days} ${hours} ${t.hours} ${minutes} ${t.minutes} ${seconds} ${t.seconds}\n\n${t.notice}`;
}
