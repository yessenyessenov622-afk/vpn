import { Bot, Context, InlineKeyboard, Keyboard } from "grammy";
import { initialLanguage, isLanguage, languageNames, Language, translations } from "./translations";
import { supportTranslations } from "./support-translations";
import { describeSubscriptionView, subscriptionTranslations, utcDate } from "./subscription-translations";
import { Subscription, SubscriptionView, VPNResponse } from "./storage";
import { paymentTranslations } from "./payment-translations";
import { plans } from "./plans";
import { planTranslations } from "./plan-translations";
import { vpnTranslations } from "./vpn-translations";
import { paymentPlans, starsPrice } from "./payment-plans";
import { executeRefund } from "./refund-flow";

export const SUPPORT_MAX_LENGTH = 3000;
export interface LanguageStorage {
  get(userId: number): Promise<Language | null>;
  set(userId: number, language: Language): Promise<void>;
  register(userId: number): Promise<void>;
  subscription(userId: number): Promise<Subscription | null>;
  subscriptionView?(userId: number): Promise<SubscriptionView>;
  grant(userId: number, days: number): Promise<Subscription | null>;
  vpnRequest(userId: number, publicKey: string): Promise<VPNResponse>;
  paymentOrder?(userId: number, planId: string, amount: number): Promise<any>;
  paymentValidate?(userId: number, orderId: string, currency: string, amount: number): Promise<boolean>;
  paymentApply?(userId: number, orderId: string, currency: string, amount: number, chargeId: string): Promise<any>;
  refundPrepare?(adminId: number, userId: number, chargeId: string): Promise<{status: string; recalc_status: string}>;
  refundBegin?(adminId: number, userId: number, chargeId: string): Promise<{status: string; ready?: boolean; amount?: number; currency?: string}>;
  refundConfirm?(userId: number, chargeId: string, amount: number, currency: string, orderId?: string): Promise<string>;
  refundReject?(adminId: number, userId: number, chargeId: string): Promise<boolean>;
}
type State = { kind: "request" } | { kind: "reply"; userId: number; fallbackLanguage: Language } | { kind: "vpn" };

export function parseAdminId(value: string | undefined): number | null {
  const text = (value || "").trim();
  if (!/^[1-9]\d*$/.test(text)) return null;
  const id = Number(text);
  return Number.isSafeInteger(id) && id <= 2 ** 52 ? id : null;
}

export function createBot(token: string, storage: LanguageStorage, adminId: number, test?: {invoices: boolean; refunds: boolean}): Bot {
  const bot = new Bot(token, test ? {client: {environment: "test"}} : undefined);
  const states = new Map<number, State>();
  function menu(language: Language): Keyboard {
    return new Keyboard().text(translations[language].menu).text(supportTranslations[language].button).row().text(subscriptionTranslations[language].button).text(planTranslations[language].button).row().text(vpnTranslations[language].button).resized();
  }
  function cancelMenu(label: string): Keyboard { return new Keyboard().text(label).resized(); }
  function choices(): InlineKeyboard {
    const keyboard = new InlineKeyboard();
    (Object.keys(languageNames) as Language[]).forEach((language, index) => {
      keyboard.text(languageNames[language], `language:${language}`);
      if (index % 2 === 1) keyboard.row();
    });
    return keyboard;
  }
  async function currentLanguage(ctx: Context): Promise<Language> {
    if (!ctx.from) throw new Error("Missing user");
    return (await storage.get(ctx.from.id)) || initialLanguage(ctx.from.language_code);
  }
  async function showChoices(ctx: Context): Promise<void> {
    const language = await currentLanguage(ctx);
    await ctx.reply(translations[language].choose, { reply_markup: choices() });
  }
  async function showPlans(ctx: Context, language: Language): Promise<void> {
    const t = planTranslations[language];
    const keyboard = new InlineKeyboard();
    for (const plan of plans) keyboard.text(`${plan.names[language]} — ${plan.days} ${t.days}`, `plans:${plan.id}`).row();
    keyboard.text(t.home, "plans:home");
    await ctx.reply(t.list, { reply_markup: keyboard });
  }

  bot.on("pre_checkout_query", async ctx => {
    const q = ctx.preCheckoutQuery;
    const languagePromise = storage.get(q.from.id).catch(() => null);
    let ok = false;
    try {
      ok = !!storage.paymentValidate && await Promise.race([
        storage.paymentValidate(q.from.id, q.invoice_payload, q.currency, q.total_amount),
        new Promise<boolean>(resolve => setTimeout(() => resolve(false), 7000)),
      ]);
    } catch (_) { /* fail closed */ }
    const language = await Promise.race([languagePromise, new Promise<null>(resolve => setTimeout(() => resolve(null), 500))]);
    await ctx.answerPreCheckoutQuery(ok, ok ? undefined : {error_message: paymentTranslations[language || initialLanguage(q.from.language_code)].checkoutError});
  });

  bot.use(async (ctx, next) => {
    if (ctx.chat?.type !== "private" || !ctx.from) return;
    try { await storage.register(ctx.from.id); await next(); }
    catch (_) {
      console.error("Не удалось обработать запрос. Проверьте Python и подключение к Telegram.");
      const fallback = initialLanguage(ctx.from.language_code);
      if (ctx.callbackQuery) await ctx.answerCallbackQuery().catch(() => undefined);
      await ctx.reply(translations[fallback].error).catch(() => undefined);
    }
  });

  bot.command("start", async ctx => {
    states.delete(ctx.from!.id);
    const language = await currentLanguage(ctx);
    await ctx.reply(translations[language].welcome, { reply_markup: menu(language) });
  });
  bot.command("help", async ctx => {
    states.delete(ctx.from!.id);
    const language = await currentLanguage(ctx);
    await ctx.reply(translations[language].help, { reply_markup: menu(language) });
  });
  bot.command("language", async ctx => { states.delete(ctx.from!.id); await showChoices(ctx); });
  if (test) bot.command("test_id", async ctx => { await ctx.reply(`TEST: ваш ID в тестовой среде: ${ctx.from!.id}`); });
  bot.command("paysupport", async ctx => {
    const language = await currentLanguage(ctx);
    await ctx.reply(paymentTranslations[language].support, {reply_markup: menu(language)});
  });
  bot.command("refund_prepare", async ctx => {
    if (ctx.from!.id !== adminId || ctx.chat?.type !== 'private' || ctx.chat.id !== adminId) return;
    const parts = ctx.match.trim().split(/\s+/);
    const user = parts.length === 2 && /^[1-9]\d*$/.test(parts[0]) ? Number(parts[0]) : NaN;
    if (!Number.isSafeInteger(user) || user > 2 ** 52 || !parts[1] || parts[1].length > 255 || !storage.refundPrepare) {
      await ctx.reply('Формат: /refund_prepare ID_пользователя ID_платежа. Реальные возвраты отключены.'); return;
    }
    try {
      const result = await storage.refundPrepare(adminId, user, parts[1]);
      const labels: Record<string,string> = {prepared:'подготовлен', uncertain:'результат неизвестен — нужна сверка истории', rejected:'отклонён Telegram', confirmed:'подтверждён Telegram'};
      const recalculation = result.recalc_status === 'manual_review' ? ' Пересчёт требует ручной проверки.' : result.recalc_status === 'applied' ? ' Срок пересчитан.' : '';
      await ctx.reply(`Статус возврата: ${labels[result.status] || 'неизвестен'}.${recalculation} Реальные возвраты отключены.`);
    } catch (_) { await ctx.reply('Не удалось подготовить возврат: проверьте пользователя и платёж. Реальные возвраты отключены.'); }
  });
  bot.command("refund_execute", async ctx => {
    if (ctx.from!.id !== adminId || ctx.chat?.type !== 'private' || ctx.chat.id !== adminId) return;
    // Hard-coded safety gate: environment variables cannot enable real refunds.
    const realRefundsEnabled: boolean = false;
    if (!realRefundsEnabled && !test?.refunds) { await ctx.reply('Реальные возвраты принудительно отключены.'); return; }
    const parts = ctx.match.trim().split(/\s+/), user = Number(parts[0]);
    if (parts.length !== 2 || !/^[1-9]\d*$/.test(parts[0]) || !Number.isSafeInteger(user) || user > 2**52 || !parts[1] || parts[1].length > 255 || !storage.refundBegin || !storage.refundConfirm || !storage.refundReject) {
      await ctx.reply('Формат: /refund_execute ID_пользователя ID_платежа.'); return;
    }
    try {
      const result = await executeRefund({refundBegin: storage.refundBegin.bind(storage), refundConfirm: storage.refundConfirm.bind(storage), refundReject: storage.refundReject.bind(storage)}, adminId, user, parts[1], (id, charge) => ctx.api.refundStarPayment(id, charge));
      await ctx.reply(`Состояние возврата: ${result}. При неопределённости проверьте историю Stars и не повторяйте запрос.`);
    } catch (_) { await ctx.reply('Операция не подтверждена. Проверьте историю Stars и состояние возврата; не повторяйте запрос автоматически.'); }
  });
  bot.command("buy", async ctx => {
    const language = await currentLanguage(ctx);
    const plan = paymentPlans.find(p => p.id === ctx.match.trim());
    const price = plan ? (test?.invoices ? 1 : starsPrice(process.env[plan.priceEnv])) : null;
    // This stage is local preparation only; a deliberate code change is required before real invoices.
    const salesReady = false;
    if (!plan || (!(salesReady && process.env.STARS_PAYMENTS_ENABLED === "1") && !test?.invoices) || price === null || !storage.paymentOrder) {
      await ctx.reply(paymentTranslations[language].unavailable); return;
    }
    try {
      const order = await storage.paymentOrder(ctx.from!.id, plan.id, price);
      const label = `${plan.days} ${planTranslations[language].days}`;
      await ctx.replyWithInvoice(test ? `TEST: ${label}` : label, test ? `TEST ONLY — ${label}; no VPN service` : `${paymentTranslations[language].paid}: ${label}`, order.order_id, "XTR", [{label, amount: price}]);
    } catch (_) { await ctx.reply(paymentTranslations[language].invoiceError); }
  });
  bot.on("message:successful_payment", async ctx => {
    const p = ctx.message.successful_payment;
    const language = await currentLanguage(ctx).catch(() => initialLanguage(ctx.from.language_code));
    try {
      if (!storage.paymentApply) throw new Error();
      const result = await storage.paymentApply(ctx.from.id, p.invoice_payload, p.currency, p.total_amount, p.telegram_payment_charge_id);
      if (result.status === "pending") {
        await ctx.reply(paymentTranslations[language].pending); return;
      }
      if (result.status !== "paid" && result.status !== "duplicate") throw new Error();
      await ctx.reply(paymentTranslations[language].recorded);
    } catch (_) {
      console.error("PAYMENT_FULFILLMENT_FAILED");
      await ctx.api.sendMessage(adminId, `Ошибка записи подтверждённого платежа. Код: payment_storage_error. ID пользователя: ${ctx.from.id}. Проверьте платёж вручную через Telegram.`).catch(() => undefined);
      await ctx.reply(paymentTranslations[language].failed).catch(() => undefined);
    }
  });
  bot.command("test_alert", async ctx => {
    if (ctx.from!.id !== adminId || ctx.chat?.type !== "private" || ctx.chat.id !== adminId) {
      const language = await currentLanguage(ctx);
      await ctx.reply(subscriptionTranslations[language].forbidden);
      return;
    }
    try {
      await ctx.api.sendMessage(adminId, "🔔 Проверка уведомлений\nЭто тестовое сообщение. Уведомления администратора работают.");
    } catch (_) {
      console.error("VPN_TEST_ALERT_DELIVERY_FAILED");
      await ctx.reply("Не удалось отправить тестовое уведомление. Проверьте доступ бота к личному чату и попробуйте позже.").catch(() => undefined);
    }
  });
  bot.command("grant_test", async ctx => {
    if (ctx.from!.id !== adminId) {
      const language = await currentLanguage(ctx);
      await ctx.reply(subscriptionTranslations[language].forbidden);
      return;
    }
    const parts = ctx.match.trim().split(/\s+/);
    const userId = parts.length === 2 ? parseAdminId(parts[0]) : null;
    const days = parts.length === 2 && /^[1-9]\d*$/.test(parts[1]) ? Number(parts[1]) : NaN;
    if (userId === null || !Number.isSafeInteger(days) || days < 1 || days > 365) {
      await ctx.reply("Использование: /grant_test TELEGRAM_ID DAYS. ID — положительное число, DAYS — от 1 до 365 дней.");
      return;
    }
    let subscription: Subscription | null;
    try { subscription = await storage.grant(userId, days); }
    catch (_) {
      await ctx.reply("Не удалось сохранить тестовую подписку. Попробуйте позже.");
      return;
    }
    if (!subscription) {
      await ctx.reply("Пользователь не зарегистрирован. Попросите его открыть бота и отправить /start.");
      return;
    }
    await ctx.reply(`Тестовая подписка для ID ${userId} выдана. Начало: ${utcDate(subscription.started_at)}. Окончание: ${utcDate(subscription.expires_at)}. Это не оплата и не VPN-доступ.`);
  });
  bot.callbackQuery(/^language:([a-z]{2})$/, async ctx => {
    const language = ctx.match[1];
    if (!isLanguage(language)) { await ctx.answerCallbackQuery(); return; }
    await storage.set(ctx.from.id, language);
    states.delete(ctx.from.id);
    await ctx.answerCallbackQuery();
    await ctx.reply(translations[language].changed, { reply_markup: menu(language) });
  });

  bot.callbackQuery(/^plans:([a-z0-9_]+)$/, async ctx => {
    const language = await currentLanguage(ctx);
    const t = planTranslations[language];
    if (states.has(ctx.from.id)) {
      await ctx.answerCallbackQuery({ text: t.busy });
      return;
    }
    const action = ctx.match[1];
    if (action === "home") {
      await ctx.answerCallbackQuery();
      await ctx.reply(t.homeMessage, { reply_markup: menu(language) });
      return;
    }
    if (action === "list") {
      await ctx.answerCallbackQuery();
      await showPlans(ctx, language);
      return;
    }
    const plan = plans.find(item => item.id === action);
    if (!plan) { await ctx.answerCallbackQuery(); return; }
    await ctx.answerCallbackQuery();
    const keyboard = new InlineKeyboard().text(t.back, "plans:list").row().text(t.home, "plans:home");
    await ctx.reply(`${plan.names[language]}\n${t.duration}: ${plan.days} ${t.days}\n\n${t.notice}`, { reply_markup: keyboard });
  });

  bot.callbackQuery(/^support_reply:(\d+):([a-z]{2})$/, async ctx => {
    if (ctx.from.id !== adminId || ctx.chat?.id !== adminId) {
      await ctx.answerCallbackQuery({ text: "Доступ запрещён." });
      return;
    }
    const target = parseAdminId(ctx.match[1]);
    const fallbackLanguage = ctx.match[2];
    if (!target || !isLanguage(fallbackLanguage)) { await ctx.answerCallbackQuery({ text: "Некорректное обращение." }); return; }
    const previous = states.get(adminId);
    states.set(adminId, { kind: "reply", userId: target, fallbackLanguage });
    await ctx.answerCallbackQuery();
    const prompt = previous?.kind === "reply" && previous.userId !== target
      ? `Выбрано другое обращение. Теперь ответ будет отправлен пользователю ID ${target}. Напишите ответ одним текстовым сообщением (до ${SUPPORT_MAX_LENGTH} символов).`
      : `Напишите ответ пользователю ID ${target} одним текстовым сообщением (до ${SUPPORT_MAX_LENGTH} символов).`;
    await ctx.reply(prompt, { reply_markup: cancelMenu("Отмена") });
  });

  bot.on("message", async ctx => {
    const userId = ctx.from.id;
    const state = states.get(userId);
    const text = "text" in ctx.message ? ctx.message.text : undefined;
    const language = await currentLanguage(ctx);
    const strings = supportTranslations[language];

    if (state) {
      if (text && (text === "Отмена" || Object.values(supportTranslations).some(item => item.cancel === text) || Object.values(vpnTranslations).some(item => item.cancel === text))) {
        states.delete(userId);
        await ctx.reply(state.kind === "reply" ? "Ответ отменён." : state.kind === "vpn" ? vpnTranslations[language].cancelled : strings.cancelled, { reply_markup: menu(language) });
        return;
      }
      if (state.kind === "vpn") {
        const vpn = vpnTranslations[language];
        if (typeof text !== "string" || !text.trim()) { await ctx.reply(vpn.textOnly); return; }
        let result: VPNResponse;
        try { result = await storage.vpnRequest(userId, text.trim()); }
        catch (_) { states.delete(userId); await ctx.reply(vpn.unavailable, {reply_markup: menu(language)}); return; }
        if (result.status === "invalid_key") { await ctx.reply(vpn.invalid); return; }
        states.delete(userId);
        const messages: Record<string, string> = {inactive:vpn.inactive, device_exists:vpn.exists, key_in_use:vpn.used, ip_in_use:vpn.noAddress, unavailable:vpn.unavailable, unconfirmed:vpn.unconfirmed};
        if (result.status !== "confirmed") { await ctx.reply(messages[result.status] || vpn.unavailable, {reply_markup: menu(language)}); return; }
        await ctx.reply(`${vpn.ready}\n${vpn.address}: ${result.address}\n${vpn.serverKey}: ${result.server_public_key}\n${vpn.endpoint}: ${result.endpoint}\n${vpn.allowed}: 0.0.0.0/0\n${vpn.dns}: 1.1.1.1\n\n${vpn.instructions}`, {reply_markup: menu(language)});
        return;
      }
      if (typeof text !== "string" || !text.trim()) {
        await ctx.reply(state.kind === "reply" ? "Пока можно отправить только текстовый ответ." : strings.textOnly);
        return;
      }
      if (text.length > SUPPORT_MAX_LENGTH) {
        await ctx.reply(state.kind === "reply" ? `Ответ слишком длинный. Максимум — ${SUPPORT_MAX_LENGTH} символов.` : strings.tooLong);
        return;
      }
      if (state.kind === "request") {
        const clean = (value: string) => value.replace(/[\r\n\t]/g, " ").slice(0, 160);
        const name = clean([ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(" ")) || "не указано";
        const username = ctx.from.username ? `@${clean(ctx.from.username)}` : "не указан";
        const date = new Date(ctx.message.date * 1000).toISOString();
        const message = `Новое обращение\nID пользователя: ${userId}\nИмя: ${name}\nUsername: ${username}\nДата (UTC): ${date}\n\n${text}`;
        let delivered = false;
        try {
          await ctx.api.sendMessage(adminId, message, { reply_markup: new InlineKeyboard().text("Ответить", `support_reply:${userId}:${language}`) });
          delivered = true;
        } catch (_) { /* Сообщаем об ошибке только после неудачной отправки. */ }
        states.delete(userId);
        await ctx.reply(delivered ? strings.sent : strings.failed, { reply_markup: menu(language) });
      } else {
        let delivered = false;
        try {
          const targetLanguage = (await storage.get(state.userId)) || state.fallbackLanguage;
          await ctx.api.sendMessage(state.userId, `${supportTranslations[targetLanguage].reply}\n\n${text}`);
          delivered = true;
        } catch (_) { /* Не подтверждаем отправку при ошибке. */ }
        states.delete(userId);
        await ctx.reply(delivered ? "Ответ отправлен пользователю." : "Не удалось отправить ответ пользователю. Попробуйте позже.", { reply_markup: menu(language) });
      }
      return;
    }
    if (!text) return;
    if (Object.values(translations).some(item => item.menu === text)) { await showChoices(ctx); return; }
    if (Object.values(vpnTranslations).some(item => item.button === text)) {
      const vpn = vpnTranslations[language];
      if (test) { await ctx.reply(vpn.unavailable, {reply_markup: menu(language)}); return; }
      const subscription = await storage.subscription(userId);
      if (!subscription || subscription.expires_at * 1000 <= Date.now()) { await ctx.reply(vpn.inactive, {reply_markup: menu(language)}); return; }
      states.set(userId, {kind: "vpn"});
      await ctx.reply(vpn.prompt, {reply_markup: cancelMenu(vpn.cancel)});
      return;
    }
    if (Object.values(planTranslations).some(item => item.button === text)) { await showPlans(ctx, language); return; }
    if (Object.values(subscriptionTranslations).some(item => item.button === text)) {
      const view = storage.subscriptionView ? await storage.subscriptionView(userId) : {subscription: await storage.subscription(userId), source: "unknown" as const, vpn: "unknown" as const};
      await ctx.reply(describeSubscriptionView(view, language));
      return;
    }
    if (Object.values(supportTranslations).some(item => item.button === text)) {
      states.set(userId, { kind: "request" });
      await ctx.reply(strings.prompt, { reply_markup: cancelMenu(strings.cancel) });
    }
  });
  bot.catch(() => { console.error("Ошибка бота. Проверьте настройки и подключение к Telegram."); });
  return bot;
}
