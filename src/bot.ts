import "dotenv/config";
import { Storage } from "./storage";
import { createBot, parseAdminId } from "./handlers";
import { AlertDispatcher } from "./alerts";
import { PaymentJournal } from "./payment-journal";
import { processBatch, replayJournal } from "./payment-polling";
import { reconcileStarHistory } from "./star-history";
import { join } from "path";

const token = (process.env.BOT_TOKEN || "").trim();
if (!token) {
  console.error("Ошибка конфигурации: укажите BOT_TOKEN в файле .env.");
  process.exit(1);
}
const adminId = parseAdminId(process.env.ADMIN_ID);
if (adminId === null) {
  console.error("Ошибка конфигурации: укажите положительный числовой Telegram ID в ADMIN_ID файла .env.");
  process.exit(1);
}

const storage = new Storage();
const bot = createBot(token, storage, adminId);
const dispatcher = new AlertDispatcher(storage, text => bot.api.sendMessage(adminId, text));
let alertsStopped = false;
let alertTimer: NodeJS.Timeout | undefined;
const checkAlerts = async (): Promise<void> => {
  await dispatcher.run();
  if (!alertsStopped) alertTimer = setTimeout(checkAlerts, 15000);
};
if (process.env.VPN_LOCAL_CONTROLLER === "1") void checkAlerts();
let historyTimer: NodeJS.Timeout | undefined;
const checkHistory = async (): Promise<void> => {
  try { await reconcileStarHistory((offset, limit) => bot.api.getStarTransactions({offset, limit}), storage); }
  catch (_) { console.error("STARS_HISTORY_RECONCILIATION_FAILED"); }
  if (!alertsStopped) historyTimer = setTimeout(checkHistory, 60000);
};
if (process.env.STARS_HISTORY_RECONCILIATION === "1") void checkHistory();
let pollingStopped = false;
const stop = () => { alertsStopped = true; pollingStopped = true; if (alertTimer) clearTimeout(alertTimer); if (historyTimer) clearTimeout(historyTimer); };
process.once("SIGINT", stop);
process.once("SIGTERM", stop);
const journal = new PaymentJournal(join(process.cwd(), "payment-journal"));
async function poll(): Promise<void> {
  let offset = 0;
  await bot.init();
  while (!pollingStopped) {
    try { await replayJournal(journal, r => storage.paymentApply(r.userId, r.orderId, r.currency, r.amount, r.chargeId)); }
    catch (_) { console.error("PAYMENT_JOURNAL_TRANSFER_FAILED"); }
    if (pollingStopped) break;
    try {
      const updates = await bot.api.getUpdates({offset, timeout: 25});
      offset = await processBatch(updates, offset, journal, async update => {
        try { await bot.handleUpdate(update); } catch (_) { console.error("BOT_UPDATE_FAILED"); }
      }, (user, charge, amount, currency, order) => storage.refundConfirm(user, charge, amount, currency, order));
    } catch (_) {
      console.error("PAYMENT_POLLING_BLOCKED_OR_NETWORK_ERROR");
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
  }
  await storage.close();
}
console.log("Бот запускается. Для остановки нажмите Ctrl+C.");
poll().catch(() => { console.error("Бот остановлен из-за ошибки запуска."); alertsStopped = true; if (alertTimer) clearTimeout(alertTimer); if (historyTimer) clearTimeout(historyTimer); storage.close(); process.exitCode = 1; });
