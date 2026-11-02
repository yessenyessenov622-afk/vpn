import { strict as assert } from "assert";
import { Bot } from "grammy";
import { initialLanguage, languageNames, translations } from "./translations";
import { supportTranslations } from "./support-translations";
import { createBot, LanguageStorage, parseAdminId } from "./handlers";
import { Language } from "./translations";
import { describeSubscription, describeSubscriptionView, subscriptionTranslations } from "./subscription-translations";
import { paymentTranslations } from "./payment-translations";
import { Storage, Subscription } from "./storage";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, rmdirSync, unlinkSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { spawnSync } from "child_process";
import { plans } from "./plans";
import { planTranslations } from "./plan-translations";
import { vpnTranslations } from "./vpn-translations";

const keys = Object.keys(translations.ru).sort().join(",");
const supportKeys = Object.keys(supportTranslations.ru).sort().join(",");
const subscriptionKeys = Object.keys(subscriptionTranslations.ru).sort().join(",");
const planKeys = Object.keys(planTranslations.ru).sort().join(",");
const vpnKeys = Object.keys(vpnTranslations.ru).sort().join(",");
const paymentKeys = Object.keys(paymentTranslations.ru).sort().join(",");
assert.equal(typeof Bot, "function");
assert.equal(Object.keys(languageNames).length, 8);
for (const code of Object.keys(languageNames) as (keyof typeof languageNames)[]) {
  assert.equal(Object.keys(translations[code]).sort().join(","), keys);
  for (const value of Object.values(translations[code])) assert.ok(value.trim());
  assert.equal(Object.keys(supportTranslations[code]).sort().join(","), supportKeys);
  for (const value of Object.values(supportTranslations[code])) assert.ok(value.trim());
  assert.equal(Object.keys(subscriptionTranslations[code]).sort().join(","), subscriptionKeys);
  for (const value of Object.values(subscriptionTranslations[code])) assert.ok(value.trim());
  assert.equal(Object.keys(planTranslations[code]).sort().join(","), planKeys);
  for (const value of Object.values(planTranslations[code])) assert.ok(value.trim());
  for (const plan of plans) assert.ok(plan.names[code].trim());
  assert.equal(Object.keys(vpnTranslations[code]).sort().join(","), vpnKeys);
  for (const value of Object.values(vpnTranslations[code])) assert.ok(value.trim());
  assert.equal(Object.keys(paymentTranslations[code]).sort().join(","), paymentKeys);
  for (const value of Object.values(paymentTranslations[code])) assert.ok(value.trim());
  for (const source of ["test", "paid", "mixed", "unknown"] as const) {
    for (const vpn of ["none", "unknown", "allowed", "revoked"] as const) {
      const screen = describeSubscriptionView({subscription: {started_at: 100, expires_at: 200}, source, vpn}, code, 150000);
      assert.ok(screen.includes(subscriptionTranslations[code].active));
      assert.ok(screen.includes(vpn === "none" ? paymentTranslations[code].vpnNone : vpn === "unknown" ? paymentTranslations[code].vpnUnknown : vpn === "allowed" ? paymentTranslations[code].vpnAllowed : paymentTranslations[code].vpnRevoked));
      assert.ok(screen.includes(source === "test" ? subscriptionTranslations[code].title : source === "paid" ? paymentTranslations[code].paid : source === "mixed" ? paymentTranslations[code].mixed : paymentTranslations[code].unknownSource));
    }
  }
  assert.ok(describeSubscriptionView({subscription: null, source: "unknown", vpn: "none"}, code).includes(paymentTranslations[code].vpnNone));
  assert.ok(describeSubscriptionView({subscription: {started_at: 100, expires_at: 200}, source: "paid", vpn: "unknown"}, code, 200000).includes(subscriptionTranslations[code].expired));
}
assert.deepEqual(plans.map(plan => plan.days), [7, 18, 30]);
assert.equal(new Set(plans.map(plan => plan.id)).size, 3);
assert.equal(initialLanguage("kk-KZ"), "kk");
assert.equal(initialLanguage("xx"), "ru");
assert.equal(parseAdminId("12345"), 12345);
for (const value of ["", "0", "-123", "1.2", "abc", "9007199254740992"]) assert.equal(parseAdminId(value), null);
const exampleSubscription = { started_at: 1700000000, expires_at: 1700000060 };
assert.ok(describeSubscription(exampleSubscription, "ru", 1700000059999).includes("Активна"));
assert.ok(describeSubscription(exampleSubscription, "ru", 1700000060000).includes("Истекла"));
assert.ok(describeSubscription(exampleSubscription, "ru", 1700000060000).includes("0 сек."));

async function testHandlers(): Promise<void> {
  const languages = new Map<number, Language>();
  const registered = new Set<number>();
  const subscriptions = new Map<number, Subscription>();
  let grants = 0, failGrant = false, vpnCalls = 0, vpnConfirmed = false;
  const storage: LanguageStorage = {
    get: async id => languages.get(id) || null,
    set: async (id, language) => { languages.set(id, language); },
    register: async id => { registered.add(id); },
    subscription: async id => subscriptions.get(id) || null,
    vpnRequest: async (id, key) => {
      vpnCalls++;
      assert.equal(id, 101);
      if (key === "invalid") return {status: "invalid_key"};
      if (vpnConfirmed) return {status: "confirmed", address: "10.77.0.3/32", server_public_key: "test-public-key", endpoint: "192.0.2.1:51820"};
      return {status: "unavailable"};
    },
    grant: async (id, days) => {
      grants++;
      if (failGrant) throw new Error("Simulated database failure");
      if (!registered.has(id)) return null;
      const now = Math.floor(Date.now() / 1000);
      const old = subscriptions.get(id);
      const active = old && old.expires_at > now;
      const result = { started_at: active ? old!.started_at : now, expires_at: (active ? old!.expires_at : now) + days * 86400 };
      subscriptions.set(id, result);
      return result;
    }
  };
  const admin = 900, one = 101, two = 202;
  let paymentValid = true, applied = 0;
  storage.paymentValidate = async (id, order, currency, amount) => paymentValid && id === one && order === "order" && currency === "XTR" && amount === 25;
  storage.paymentApply = async (id, order, currency, amount, charge) => {
    if (id !== one || order !== "order" || currency !== "XTR" || amount !== 25 || charge !== "charge") throw new Error("invalid");
    applied++; return {status: "paid"};
  };
  const bot = createBot("123456:example", storage, admin);
  bot.botInfo = { id: 123456, is_bot: true, first_name: "Test", username: "test_bot", can_join_groups: true, can_read_all_group_messages: false, supports_inline_queries: false, can_connect_to_business: false, has_main_web_app: false };
  const calls: Array<{ method: string; payload: any }> = [];
  let failRecipient: number | null = null, failTestAlertOnce = false;
  bot.api.config.use(async (_previous, method, payload) => {
    calls.push({ method, payload });
    if (method === "sendMessage" && failTestAlertOnce && (payload as any).text?.includes("🔔 Проверка уведомлений")) { failTestAlertOnce = false; throw new Error("Simulated delivery failure"); }
    if (method === "sendMessage" && (payload as any).chat_id === failRecipient) throw new Error("Simulated delivery failure");
    if (method === "sendMessage") return { ok: true, result: { message_id: calls.length } } as any;
    if (method === "answerCallbackQuery") return { ok: true, result: true } as any;
    if (method === "answerPreCheckoutQuery") return { ok: true, result: true } as any;
    throw new Error("Unexpected API call");
  });
  let updateId = 0;
  async function message(id: number, text?: string, language = "ru"): Promise<void> {
    const content = text === undefined ? { photo: [{ file_id: "fake", file_unique_id: "fake", width: 1, height: 1 }] } : { text, ...(text.startsWith("/") ? { entities: [{ type: "bot_command", offset: 0, length: text.split(" ")[0].length }] } : {}) };
    await bot.handleUpdate({ update_id: ++updateId, message: { message_id: updateId, date: 1700000000, chat: { id, type: "private" }, from: { id, is_bot: false, first_name: "Test", language_code: language }, ...content } } as any);
  }
  async function click(id: number, data: string): Promise<void> {
    await bot.handleUpdate({ update_id: ++updateId, callback_query: { id: String(updateId), from: { id, is_bot: false, first_name: "Test" }, chat_instance: "test", data, message: { message_id: 1, date: 1700000000, chat: { id, type: "private" } } } } as any);
  }
  const sent = () => calls.filter(call => call.method === "sendMessage");
  const last = () => sent()[sent().length - 1].payload;

  let refundCalls = 0;
  storage.refundPrepare = async (actor, user, charge) => {
    refundCalls++;
    assert.equal(actor, admin); assert.equal(user, one); assert.equal(charge, "charge");
    return {status: "prepared", recalc_status: "pending"};
  };
  await message(one, "/refund_prepare 101 charge");
  assert.equal(refundCalls, 0);
  await message(admin, "/refund_prepare 101 charge");
  assert.equal(refundCalls, 1);
  assert.ok(last().text.includes("Реальные возвраты отключены"));
  await message(admin, "/refund_execute 101 charge");
  assert.ok(last().text.includes("принудительно отключены"));
  assert.equal(calls.filter(call => call.method === "refundStarPayment").length, 0);

  storage.subscriptionView = async id => ({subscription: subscriptions.get(id) || null, source: "unknown", vpn: "none"});
  for (const [index, language] of (Object.keys(languageNames) as Language[]).entries()) {
    const user = 1000 + index;
    languages.set(user, language);
    await message(user, "/paysupport");
    assert.equal(last().text, paymentTranslations[language].support);
    await message(user, "/buy days7");
    assert.equal(last().text, paymentTranslations[language].unavailable);
    await message(user, subscriptionTranslations[language].button);
    assert.ok(last().text.includes(paymentTranslations[language].vpnNone));
    subscriptions.set(user, {started_at: 1, expires_at: 2});
    storage.subscriptionView = async id => ({subscription: subscriptions.get(id) || null, source: "paid", vpn: "unknown"});
    await message(user, subscriptionTranslations[language].button);
    assert.ok(last().text.includes(paymentTranslations[language].paid));
    assert.ok(last().text.includes(paymentTranslations[language].vpnUnknown));
    assert.ok(last().text.includes(subscriptionTranslations[language].expired));
    subscriptions.delete(user);
    storage.subscriptionView = async id => ({subscription: subscriptions.get(id) || null, source: "unknown", vpn: "none"});
  }
  storage.subscriptionView = undefined;

  await message(one, "/buy days7");
  assert.equal(last().text, paymentTranslations.ru.unavailable);
  assert.equal(calls.filter(call => call.method === "sendInvoice").length, 0);
  await bot.handleUpdate({update_id: ++updateId, pre_checkout_query: {id: "checkout", from: {id: one, is_bot: false, first_name: "Test"}, currency: "XTR", total_amount: 25, invoice_payload: "order"}} as any);
  assert.equal(calls[calls.length - 1].method, "answerPreCheckoutQuery");
  assert.equal(calls[calls.length - 1].payload.ok, true);
  assert.equal(applied, 0);
  paymentValid = false;
  await bot.handleUpdate({update_id: ++updateId, pre_checkout_query: {id: "checkout2", from: {id: one, is_bot: false, first_name: "Test"}, currency: "XTR", total_amount: 25, invoice_payload: "order"}} as any);
  assert.equal(calls[calls.length - 1].payload.ok, false);
  paymentValid = true;
  await bot.handleUpdate({update_id: ++updateId, message: {message_id: updateId, date: 1700000000, chat: {id: one, type: "private"}, from: {id: one, is_bot: false, first_name: "Test"}, successful_payment: {currency: "XTR", total_amount: 25, invoice_payload: "order", telegram_payment_charge_id: "charge", provider_payment_charge_id: ""}}} as any);
  assert.equal(applied, 1);

  await message(admin, "/test_alert");
  assert.equal(last().chat_id, admin);
  assert.ok(last().text.includes("Это тестовое сообщение"));
  const testAlerts = () => sent().filter(call => call.payload.text.includes("🔔 Проверка уведомлений"));
  const alertsBefore = testAlerts().length;
  await message(one, "/test_alert");
  assert.equal(last().text, subscriptionTranslations.ru.forbidden);
  assert.equal(testAlerts().length, alertsBefore);
  const callsBeforeGroup = calls.length;
  await bot.handleUpdate({update_id: ++updateId, message: {message_id: updateId, date: 1700000000, chat: {id: -100, type: "group", title: "Test"}, from: {id: admin, is_bot: false, first_name: "Admin"}, text: "/test_alert", entities: [{type: "bot_command", offset: 0, length: 11}]}} as any);
  assert.equal(calls.length, callsBeforeGroup);
  failTestAlertOnce = true;
  await message(admin, "/test_alert");
  assert.ok(last().text.includes("Не удалось отправить тестовое уведомление"));
  assert.equal(grants, 0);
  assert.equal(vpnCalls, 0);

  await message(one, "/language");
  assert.equal(last().text, translations.ru.choose);
  await click(one, "language:en");
  assert.equal(languages.get(one), "en");
  assert.equal(last().text, translations.en.changed);
  await message(one, "/start");
  assert.equal(last().text, translations.en.welcome);
  assert.ok(JSON.stringify(last().reply_markup).includes(supportTranslations.en.button));
  assert.ok(JSON.stringify(last().reply_markup).includes(subscriptionTranslations.en.button));
  assert.ok(JSON.stringify(last().reply_markup).includes(planTranslations.en.button));
  assert.ok(JSON.stringify(last().reply_markup).includes(vpnTranslations.en.button));
  await message(one, vpnTranslations.en.button);
  assert.equal(last().text, vpnTranslations.en.inactive);
  assert.equal(vpnCalls, 0);
  await message(one, planTranslations.en.button);
  assert.equal(last().text, planTranslations.en.list);
  const listButtons = last().reply_markup.inline_keyboard.flat().map((button: any) => button.callback_data);
  assert.deepEqual(listButtons, ["plans:one", "plans:three", "plans:six", "plans:home"]);
  for (const plan of plans) {
    await click(one, `plans:${plan.id}`);
    assert.ok(last().text.includes(plan.names.en));
    assert.ok(last().text.includes(`${plan.days} ${planTranslations.en.days}`));
    assert.ok(last().text.includes(planTranslations.en.notice));
    assert.deepEqual(last().reply_markup.inline_keyboard.flat().map((button: any) => button.callback_data), ["plans:list", "plans:home"]);
    await click(one, "plans:list");
    assert.equal(last().text, planTranslations.en.list);
  }
  await click(one, "plans:home");
  assert.equal(last().text, planTranslations.en.homeMessage);
  assert.ok(JSON.stringify(last().reply_markup).includes(translations.en.menu));
  assert.equal(subscriptions.size, 0);
  assert.equal(grants, 0);
  let languageUser = 300;
  for (const code of Object.keys(languageNames) as Language[]) {
    const user = languageUser++;
    languages.set(user, code);
    await message(user, planTranslations[code].button);
    assert.equal(last().text, planTranslations[code].list);
    for (const plan of plans) {
      await click(user, `plans:${plan.id}`);
      assert.ok(last().text.includes(plan.names[code]));
      assert.ok(last().text.includes(`${plan.days} ${planTranslations[code].days}`));
      assert.ok(last().text.includes(planTranslations[code].notice));
    }
    await click(user, "plans:list");
    assert.equal(last().text, planTranslations[code].list);
    await click(user, "plans:home");
    assert.equal(last().text, planTranslations[code].homeMessage);
  }
  assert.equal(subscriptions.size, 0);
  assert.equal(grants, 0);
  await message(one, subscriptionTranslations.en.button);
  assert.ok(last().text.includes(subscriptionTranslations.en.none));
  await message(one, `/grant_test ${one} 7`);
  assert.equal(last().text, subscriptionTranslations.en.forbidden);
  assert.equal(grants, 0);
  for (const command of ["/grant_test", "/grant_test 101 0", "/grant_test 101 366", "/grant_test 101 -1", "/grant_test 101 1.5", "/grant_test abc 2", "/grant_test 101 1 extra"]) {
    await message(admin, command);
    assert.ok(last().text.includes("от 1 до 365"));
  }
  assert.equal(grants, 0);
  await message(admin, "/grant_test 55555 7");
  assert.ok(last().text.includes("не зарегистрирован"));
  await message(admin, `/grant_test ${one} 7`);
  assert.ok(last().text.includes("Тестовая подписка"));
  const firstEnd = subscriptions.get(one)!.expires_at;
  await message(admin, `/grant_test ${one} 2`);
  assert.equal(subscriptions.get(one)!.expires_at, firstEnd + 2 * 86400);
  await message(one, subscriptionTranslations.en.button);
  assert.ok(last().text.includes(paymentTranslations.en.unknownSource));
  assert.ok(last().text.includes("Active"));
  assert.ok(last().text.includes("UTC"));
  failGrant = true;
  await message(admin, `/grant_test ${one} 1`);
  assert.ok(last().text.includes("Не удалось сохранить"));
  assert.equal(subscriptions.get(one)!.expires_at, firstEnd + 2 * 86400);
  failGrant = false;
  await message(one, vpnTranslations.en.button);
  assert.equal(last().text, vpnTranslations.en.prompt);
  await message(one, "invalid");
  assert.equal(last().text, vpnTranslations.en.invalid);
  await message(one, vpnTranslations.en.cancel);
  assert.equal(last().text, vpnTranslations.en.cancelled);
  await message(one, vpnTranslations.en.button);
  await message(one, "public-test-key");
  assert.equal(last().text, vpnTranslations.en.unavailable);
  assert.equal(vpnCalls, 2);
  vpnConfirmed = true;
  await message(one, vpnTranslations.en.button);
  await message(one, "public-test-key");
  assert.ok(last().text.includes("10.77.0.3/32"));
  assert.ok(last().text.includes("192.0.2.1:51820"));
  assert.ok(last().text.includes(vpnTranslations.en.instructions));
  const savedSubscription = { ...subscriptions.get(one)! };
  const grantsBeforePlans = grants;
  await message(one, planTranslations.en.button);
  await click(one, "plans:six");
  await click(one, "plans:home");
  assert.deepEqual(subscriptions.get(one), savedSubscription);
  assert.equal(grants, grantsBeforePlans);

  await message(one, supportTranslations.en.button);
  await click(one, "plans:one"); // Старые кнопки не прерывают обращение.
  assert.equal(calls[calls.length - 1].payload.text, planTranslations.en.busy);
  await message(one); // Фото не отправляется администратору.
  assert.equal(last().text, supportTranslations.en.textOnly);
  await message(one, "x".repeat(3001));
  assert.equal(last().text, supportTranslations.en.tooLong);
  await message(one, "Problem <b>one</b>");
  const requestOne = sent().find(call => call.payload.chat_id === admin && call.payload.text.includes("Problem <b>one</b>"));
  assert.ok(requestOne);
  assert.equal(requestOne!.payload.parse_mode, undefined);
  assert.ok(requestOne!.payload.text.includes(`ID пользователя: ${one}`));
  assert.ok(requestOne!.payload.text.includes("Имя: Test"));
  assert.ok(requestOne!.payload.text.includes("Дата (UTC): 2023-11-14"));
  assert.equal(last().text, supportTranslations.en.sent);
  const firstButton = requestOne!.payload.reply_markup.inline_keyboard[0][0].callback_data;

  await message(two, supportTranslations.ru.button);
  await message(two, "Problem two");
  const requestTwo = sent().find(call => call.payload.chat_id === admin && call.payload.text.includes("Problem two"));
  assert.ok(requestTwo);
  const secondButton = requestTwo!.payload.reply_markup.inline_keyboard[0][0].callback_data;
  await click(one, firstButton); // Чужая кнопка не начинает режим администратора.
  assert.equal(calls[calls.length - 1].payload.text, "Доступ запрещён.");
  await click(admin, firstButton);
  await click(admin, secondButton);
  assert.ok(last().text.includes(`Теперь ответ будет отправлен пользователю ID ${two}`));
  await message(admin, "Answer for two");
  assert.ok(sent().some(call => call.payload.chat_id === two && call.payload.text.includes("Answer for two")));
  assert.ok(!sent().some(call => call.payload.chat_id === one && call.payload.text.includes("Answer for two")));
  assert.equal(last().text, "Ответ отправлен пользователю.");

  await click(admin, firstButton);
  await message(admin);
  assert.equal(last().text, "Пока можно отправить только текстовый ответ.");
  await message(admin, "Answer for one");
  assert.ok(sent().some(call => call.payload.chat_id === one && call.payload.text === "Support reply:\n\nAnswer for one"));

  await click(admin, firstButton);
  await message(admin, "Отмена");
  assert.equal(last().text, "Ответ отменён.");
  await message(admin, "Not a reply");
  assert.ok(!sent().some(call => call.payload.chat_id === one && call.payload.text.includes("Not a reply")));
  await message(one, supportTranslations.en.button);
  await message(one, supportTranslations.en.cancel);
  assert.equal(last().text, supportTranslations.en.cancelled);

  failRecipient = admin;
  await message(one, supportTranslations.en.button);
  await message(one, "Undeliverable request");
  assert.equal(last().text, supportTranslations.en.failed);
  failRecipient = one;
  await click(admin, firstButton);
  await message(admin, "Undeliverable reply");
  assert.equal(last().text, "Не удалось отправить ответ пользователю. Попробуйте позже.");
  console.log("Переводы, команды, доступ, доставка и отмена: OK");
}

async function testPythonBridge(): Promise<void> {
  const temp = mkdtempSync(join(tmpdir(), "vpn-bot-test-"));
  const files = ["app/__init__.py", "app/database.py", "app/vpn_devices.py", "app/vpn_policy.py", "app/vpn_provision.py", "app/vpn_alerts.py", "app/payments.py", "app/refunds.py", "app/star_history.py", "storage/service.py"];
  mkdirSync(join(temp, "app"));
  mkdirSync(join(temp, "storage"));
  for (const file of files) copyFileSync(file, join(temp, file));
  let storage: Storage | undefined;
  try {
    storage = new Storage(temp);
    await storage.register(123);
    assert.equal(await storage.get(123), null);
    await storage.set(123, "kk");
    const granted = await storage.grant(123, 7);
    assert.ok(granted);
    assert.equal(await storage.grant(456, 7), null);
    await storage.close();
    storage = new Storage(temp);
    assert.equal(await storage.get(123), "kk");
    assert.deepEqual(await storage.subscription(123), granted);
    const order = await storage.paymentOrder(123, "days7", 25);
    await storage.paymentApply(123, order.order_id, "XTR", 25, "refund-test-charge");
    const {processBatch} = await import("./payment-polling");
    const update = {update_id: 1, message: {chat: {id:123, type:"private"}, refunded_payment: {currency:"XTR", total_amount:25, invoice_payload:order.order_id, telegram_payment_charge_id:"refund-test-charge"}}};
    const confirm = (id: number, charge: string, amount: number, currency: string, payload: string) => storage!.refundConfirm(id,charge,amount,currency,payload);
    assert.equal(await processBatch([update], 0, {} as any, async () => {}, confirm), 2);
    await storage.close(); storage = new Storage(temp);
    assert.equal(await processBatch([update], 0, {} as any, async () => {}, confirm), 2);
    assert.deepEqual(await storage.subscription(123), granted);
    console.log("TypeScript + Python + временная SQLite после перезапуска: OK");
  } finally {
    if (storage) await storage.close();
    for (const file of [...files, "users.sqlite3"]) {
      const target = join(temp, file);
      if (existsSync(target)) unlinkSync(target);
    }
    rmdirSync(join(temp, "app"));
    rmdirSync(join(temp, "storage"));
    rmdirSync(temp);
  }
}

async function testAlertDelivery(): Promise<void> {
  const { AlertDispatcher, formatTestQueueMessage } = await import("./alerts");
  const event = {user_id: 101, action: "revoke", code: "unconfirmed", active: 1, occurred_at: 1000, resolved_at: null, version: 1, phase: "failure" as const};
  const formatted = formatTestQueueMessage("Проверка");
  assert.equal(formatted, "🧪 ТЕСТ ОЧЕРЕДИ — реальной ошибки VPN нет.\n\nПроверка");
  assert.ok(!formatted.includes("\\n"));
  let pending = true, attempts = 0, acknowledged = 0;
  const dispatcher = new AlertDispatcher({
    alertsDue: async () => pending ? [event] : [],
    alertsAck: async () => { acknowledged++; pending = false; },
  }, async () => { attempts++; if (attempts === 1) throw new Error("delivery failure"); });
  await dispatcher.run();
  assert.equal(acknowledged, 0);
  await dispatcher.run();
  assert.equal(acknowledged, 1);
  await dispatcher.run();
  assert.equal(attempts, 2);
  console.log("Уведомления: ошибка доставки и повторная попытка OK");
}

async function testAlertQueueIntegration(): Promise<void> {
  const { AlertDispatcher, formatTestQueueMessage } = await import("./alerts");
  const temp = mkdtempSync(join(tmpdir(), "vpn-alert-test-"));
  const files = ["app/__init__.py", "app/database.py", "app/vpn_devices.py", "app/vpn_policy.py", "app/vpn_provision.py", "app/vpn_alerts.py", "app/vpn_reconcile.py", "app/payments.py", "app/refunds.py", "app/star_history.py", "storage/service.py"];
  mkdirSync(join(temp, "app")); mkdirSync(join(temp, "storage"));
  for (const file of files) copyFileSync(file, join(temp, file));
  const setup = `import base64,sqlite3,time\nfrom app import database,vpn_reconcile\np='users.sqlite3'; now=int(time.time()); database.initialize(p); database.register_user(101,p)\nk=base64.b64encode(bytes([1])*32).decode()\nwith sqlite3.connect(p) as c:\n c.execute("INSERT INTO test_subscriptions VALUES(101,?,?)",(now-100,now-1))\n c.execute("INSERT INTO vpn_devices(user_id,public_key,created_at,updated_at,access_state,vpn_ip,server_id) VALUES(101,?,?,?,'allowed','10.77.0.3/32','primary')",(k,now,now))\nclass C:\n def is_owned(self,k,a): return True\n def list_peers(self): raise TimeoutError()\nassert vpn_reconcile.reconcile_one(101,C(),path=p)=='error'`;
  const runPython = (script: string) => { const result = spawnSync("python", ["-c", script], {cwd: temp, env: {...process.env, PYTHONDONTWRITEBYTECODE: "1"}}); assert.equal(result.status, 0); };
  let storage: Storage | undefined;
  try {
    runPython(setup);
    storage = new Storage(temp);
    let attempts = 0; const sent: string[] = [];
    const send = async (text: string) => { attempts++; if (attempts === 1) throw new Error("Telegram unavailable"); sent.push(formatTestQueueMessage(text)); };
    let dispatcher = new AlertDispatcher(storage, send);
    await dispatcher.run(); assert.equal((await storage.alertsDue()).length, 1);
    await dispatcher.run(); assert.equal(sent.length, 1); assert.ok(sent[0].includes("101")); assert.ok(sent[0].includes("нет.\n\n⚠️"));
    await dispatcher.run(); assert.equal(sent.length, 1);
    await storage.close(); storage = new Storage(temp); dispatcher = new AlertDispatcher(storage, send);
    assert.equal((await storage.alertsDue()).length, 0);
    runPython("import sqlite3,time\nwith sqlite3.connect('users.sqlite3') as c: c.execute('UPDATE vpn_alerts SET last_sent=?',(int(time.time())-3600,))");
    await dispatcher.run(); assert.equal(sent.length, 2);
    runPython("import sqlite3,time\nfrom app import vpn_alerts\nwith sqlite3.connect('users.sqlite3') as c: vpn_alerts.resolve(c,101,int(time.time()))");
    await dispatcher.run(); await dispatcher.run(); assert.equal(sent.length, 3); assert.ok(sent[2].includes("Проблема устранена"));
    console.log("Очередь SQLite + Python + отправка и восстановление: OK");
  } finally {
    if (storage) await storage.close();
    for (const file of [...files, "users.sqlite3"]) { const target = join(temp, file); if (existsSync(target)) unlinkSync(target); }
    rmdirSync(join(temp, "app")); rmdirSync(join(temp, "storage")); rmdirSync(temp);
  }
}

async function testPaymentJournal(): Promise<void> {
  const { PaymentJournal } = await import("./payment-journal");
  const { processBatch, replayJournal } = await import("./payment-polling");
  const parent = mkdtempSync(join(tmpdir(), "vpn-journal-"));
  const dir = join(parent, "journal");
  const journal = new PaymentJournal(dir);
  const update = {update_id: 17, message: {from: {id: 101}, successful_payment: {invoice_payload: "order", currency: "XTR", total_amount: 25, telegram_payment_charge_id: "charge"}}};
  let handled = 0;
  try {
    if (process.platform === "win32") assert.throws(() => new PaymentJournal(parent).record({userId: 101, orderId: "order", currency: "XTR", amount: 25, chargeId: "unsafe"}));
    assert.equal(await processBatch([update], 0, journal, async () => { handled++; }), 18);
    await processBatch([update], 0, journal, async () => { handled++; });
    assert.equal(journal.pending().length, 1);
    const {readdirSync, chmodSync} = await import("fs");
    const protectedFile = join(dir, readdirSync(dir)[0]);
    if (process.platform === "win32") {
      assert.equal(spawnSync("icacls", [protectedFile, "/grant", "*S-1-1-0:(R)"], {stdio:"ignore"}).status, 0);
      assert.throws(() => journal.pending());
      assert.equal(spawnSync("icacls", [protectedFile, "/remove", "*S-1-1-0"], {stdio:"ignore"}).status, 0);
    } else {
      chmodSync(protectedFile, 0o644); assert.throws(() => journal.pending()); chmodSync(protectedFile, 0o600);
    }
    const restarted = new PaymentJournal(dir);
    await assert.rejects(replayJournal(restarted, async () => { throw new Error("db unavailable"); }));
    assert.equal(restarted.pending().length, 1);
    await replayJournal(restarted, async () => ({status: "pending"}));
    assert.equal(restarted.pending().length, 0);
    const invalid = new PaymentJournal(join(dir, "missing", "cannot", "write"));
    const blocked = { record: () => { throw new Error("journal unavailable"); } } as unknown as InstanceType<typeof PaymentJournal>;
    await assert.rejects(processBatch([update], 0, blocked, async () => { handled++; }));
    assert.equal(handled, 2);
    assert.equal(invalid.pending().length, 0);
    console.log("Журнал платежей: повтор, перезапуск и отказ хранилища OK");
  } finally {
    for (const receipt of journal.pending()) journal.remove(receipt);
    rmdirSync(dir);
    rmdirSync(parent);
  }
}

async function testStarHistoryPages(): Promise<void> {
  const { reconcileStarHistory } = await import("./star-history");
  const item = (id: string) => ({id, amount: 25, date: 1000, source: {type: "user", transaction_type: "invoice_payment", user: {id: 101}, invoice_payload: "order"}});
  const items = [item("a"), item("b"), item("c")];
  const seen = new Map<string, any>(); let finalized = 0, inserted = false;
  const store = {starObserve: async (entry: any) => {seen.set(entry.direction + entry.id, entry);}, starFinalize: async () => {finalized++;}};
  await reconcileStarHistory(async (offset, limit) => {
    if (offset === 2 && !inserted) {items.unshift(item("new")); inserted = true;}
    return {transactions: items.slice(offset, offset + limit)};
  }, store, 2);
  assert.equal(finalized, 1); assert.deepEqual([...seen.keys()].sort(), ["incominga","incomingb","incomingc","incomingnew"]);
  let fail = true;
  await assert.rejects(reconcileStarHistory(async (offset, limit) => {if (offset > 0 && fail) throw new Error("offline"); return {transactions: items.slice(offset, offset + limit)};}, store, 2));
  assert.equal(finalized, 1); fail = false;
  await reconcileStarHistory(async (offset, limit) => ({transactions: items.slice(offset, offset + limit)}), store, 2);
  assert.equal(finalized, 2);
  const outgoing = {id: "ref", amount: 25, date: 1001, receiver: {type: "user", transaction_type: "invoice_payment", user: {id: 101}}};
  const invalidOutgoing = {id: "other", amount: 25, date: 1001, receiver: {type: "other", user: {id: 101}}};
  await reconcileStarHistory(async (offset, limit) => ({transactions: [outgoing, invalidOutgoing].slice(offset, offset + limit)}), store, 2);
  assert.ok(seen.has("outgoingref")); assert.ok(seen.has("unknownother"));
  await assert.rejects(reconcileStarHistory(async () => ({transactions: [item("x")]}), {starObserve: async () => {throw new Error("database unavailable");}, starFinalize: async () => {throw new Error("must not run");}}, 2));
  console.log("История Stars: страницы, перекрытие и восстановление после ошибки OK");
}

async function testJournalProcessCrash(): Promise<void> {
  const { PaymentJournal } = await import("./payment-journal");
  const { replayJournal } = await import("./payment-polling");
  const dir = mkdtempSync(join(tmpdir(), "vpn-journal-crash-"));
  const files = ["app/__init__.py", "app/database.py", "app/vpn_devices.py", "app/vpn_policy.py", "app/vpn_provision.py", "app/vpn_alerts.py", "app/payments.py", "app/refunds.py", "app/star_history.py", "storage/service.py"];
  mkdirSync(join(dir,"app")); mkdirSync(join(dir,"storage"));
  for (const file of files) copyFileSync(file,join(dir,file));
  const setup = spawnSync("python", ["-c", "from app import database,payments\ndatabase.initialize(); database.register_user(101); print(payments.create_order(101,'days7',25)['order_id'])"], {cwd:dir,encoding:"utf8",env:{...process.env,PYTHONDONTWRITEBYTECODE:"1"}});
  assert.equal(setup.status,0);
  const receipt = {userId: 101, orderId: setup.stdout.trim(), currency: "XTR", amount: 25, chargeId: "charge"};
  const journalDir = join(dir,"journal");
  const code = `const {PaymentJournal}=require(${JSON.stringify(join(process.cwd(), "dist", "payment-journal.js"))}); new PaymentJournal(process.argv[1]).record(${JSON.stringify(receipt)}); process.kill(process.pid, "SIGKILL");`;
  const child = spawnSync(process.execPath, ["-e", code, journalDir]);
  let storage: Storage | undefined;
  try {
    assert.equal(child.error, undefined);
    assert.ok((child.status !== null && child.status !== 0) || child.signal === "SIGKILL");
    const reopened = new PaymentJournal(journalDir);
    assert.deepEqual(reopened.pending(), [receipt]);
    if (process.platform !== "win32") {
      const { statSync, readdirSync } = await import("fs");
      assert.equal(statSync(join(journalDir,readdirSync(journalDir)[0])).mode & 0o077, 0);
    } else {
      const { readdirSync } = await import("fs");
      const acl = spawnSync("icacls", [join(journalDir,readdirSync(journalDir)[0]), "/verify"], {stdio:"ignore"});
      assert.equal(acl.status, 0); // Verifies ACL structure, not privacy of inherited permissions.
    }
    storage = new Storage(dir);
    await replayJournal(reopened, r => storage!.paymentApply(r.userId,r.orderId,r.currency,r.amount,r.chargeId));
    assert.equal(reopened.pending().length,0);
    assert.ok(await storage.subscription(101));
    console.log("Аварийный выход процесса и восстановление в SQLite: OK");
  } finally {
    if (storage) await storage.close();
    for (const file of [...files,"users.sqlite3"]) {const target=join(dir,file); if(existsSync(target)) unlinkSync(target);}
    rmdirSync(journalDir); rmdirSync(join(dir,"app")); rmdirSync(join(dir,"storage")); rmdirSync(dir);
  }
}

async function testRefundFlow(): Promise<void> {
  const {executeRefund} = await import("./refund-flow");
  const {processBatch} = await import("./payment-polling");
  let state = "prepared", calls = 0, failBegin = false, failConfirm = false;
  const store = {
    refundBegin: async () => { if (failBegin) throw new Error("db unavailable"); if (state !== "prepared") return {status: state}; state = "uncertain"; return {status: state, ready: true, amount: 25, currency: "XTR"}; },
    refundConfirm: async () => { if (failConfirm) throw new Error("db unavailable"); state = "confirmed"; return "applied"; },
    refundReject: async () => { state = "rejected"; return true; }
  };
  const send = async () => { calls++; return true; };
  failBegin = true; await assert.rejects(executeRefund(store, 9, 1, "charge", send)); assert.equal(calls, 0);
  failBegin = false; failConfirm = true;
  assert.equal(await executeRefund(store, 9, 1, "charge", send), "uncertain"); assert.equal(calls, 1);
  failConfirm = false;
  assert.equal(await executeRefund(store, 9, 1, "charge", send), "uncertain"); assert.equal(calls, 1);
  state = "prepared"; assert.equal(await executeRefund(store, 9, 1, "charge", async () => false), "rejected");
  state = "prepared"; assert.equal(await executeRefund(store, 9, 1, "charge", async () => {throw new Error("lost response");}), "uncertain");
  state = "prepared"; assert.equal(await executeRefund(store, 9, 1, "charge", send), "applied");
  const update = {update_id: 77, message: {chat: {id: 1, type: "private"}, refunded_payment: {currency: "XTR", total_amount: 25, invoice_payload: "order", telegram_payment_charge_id: "charge"}}};
  const journal = {record: () => {}} as any;
  let handled = 0, persisted = 0;
  await assert.rejects(processBatch([update], 0, journal, async () => {handled++;}, async () => {throw new Error("db down");}));
  assert.equal(handled, 0);
  const confirm = async (user: number, charge: string, amount: number, currency: string, order: string) => {assert.deepEqual([user,charge,amount,currency,order],[1,"charge",25,"XTR","order"]); persisted++; return "applied";};
  assert.equal(await processBatch([update], 0, journal, async () => {handled++;}, confirm), 78);
  assert.equal(await processBatch([update], 0, journal, async () => {handled++;}, confirm), 78);
  assert.equal(persisted, 2);
  await assert.rejects(processBatch([update], 0, journal, async () => {handled++;}));
}

async function main(): Promise<void> { await testHandlers(); await testPythonBridge(); await testAlertDelivery(); await testAlertQueueIntegration(); await testPaymentJournal(); await testStarHistoryPages(); await testJournalProcessCrash(); await testRefundFlow(); }
main().catch(error => { console.error(error); process.exitCode = 1; });
