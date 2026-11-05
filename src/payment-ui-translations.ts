import { Language } from "./translations";

export const paymentUiTranslations: Record<Language, {readyList: string; readyNotice: string; buy: string}> = {
  kk: {readyList:"Жазылу мерзімін таңдаңыз. Төлем Telegram Stars арқылы бір рет жасалады.", readyNotice:"Бір реттік төлем Telegram Stars арқылы жасалады. Мерзім Telegram төлемді растағаннан кейін қосылады.", buy:"💳 Төлеу"},
  ru: {readyList:"Выберите срок подписки. Оплата — одним платежом в Telegram Stars.", readyNotice:"Разовая оплата в Telegram Stars. Срок добавится после подтверждения платежа Telegram.", buy:"💳 Оплатить"},
  en: {readyList:"Choose a subscription period. Pay once with Telegram Stars.", readyNotice:"One-time payment in Telegram Stars. The period is added after Telegram confirms the payment.", buy:"💳 Pay"},
  tr: {readyList:"Abonelik süresini seçin. Telegram Stars ile tek seferde ödeme yapın.", readyNotice:"Telegram Stars ile tek seferlik ödeme. Süre, Telegram ödemeyi onayladıktan sonra eklenir.", buy:"💳 Öde"},
  uz: {readyList:"Obuna muddatini tanlang. Telegram Stars orqali bir marta to‘lang.", readyNotice:"Telegram Stars orqali bir martalik to‘lov. Muddat Telegram to‘lovni tasdiqlagach qo‘shiladi.", buy:"💳 To‘lash"},
  ky: {readyList:"Жазылуу мөөнөтүн тандаңыз. Telegram Stars менен бир жолу төлөңүз.", readyNotice:"Telegram Stars менен бир жолку төлөм. Мөөнөт Telegram төлөмдү ырастагандан кийин кошулат.", buy:"💳 Төлөө"},
  de: {readyList:"Wählen Sie die Laufzeit. Zahlen Sie einmalig mit Telegram Stars.", readyNotice:"Einmalige Zahlung mit Telegram Stars. Die Laufzeit wird nach Bestätigung durch Telegram hinzugefügt.", buy:"💳 Bezahlen"},
  es: {readyList:"Elige la duración. Paga una sola vez con Telegram Stars.", readyNotice:"Pago único con Telegram Stars. El periodo se añadirá cuando Telegram confirme el pago.", buy:"💳 Pagar"}
};
