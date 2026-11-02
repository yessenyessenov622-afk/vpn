import { existsSync, readFileSync } from "fs";
import { join, resolve } from "path";
import { parse } from "dotenv";
import { Storage } from "./storage";
import { createBot } from "./handlers";
import { PaymentJournal } from "./payment-journal";
import { processBatch, replayJournal } from "./payment-polling";
import { reconcileStarHistory } from "./star-history";
import { prepareSandbox, validateSettingsFile, validateTestConfig } from "./stars-isolation";

async function main(): Promise<void> {
  const project = resolve(__dirname, "..");
  const sandbox = prepareSandbox(project);
  const config = parse(readFileSync(validateSettingsFile(project,sandbox)));
  // Require proof of the production identity to reject even a rotated token for the same bot.
  const envPath = join(project,".env");
  const fileProduction = existsSync(envPath) ? parse(readFileSync(envPath)).BOT_TOKEN : undefined;
  const production = process.env.BOT_TOKEN || fileProduction;
  const settings = validateTestConfig(config, production, fileProduction);
  const storage = new Storage(sandbox, {VPN_LOCAL_CONTROLLER:"0", ADMIN_ID:String(settings.admin), STARS_PAYMENTS_ENABLED:"0", STARS_HISTORY_RECONCILIATION:"0"});
  const bot = createBot(settings.token, storage, settings.admin, {invoices:settings.invoices, refunds:settings.refunds});
  const journal = new PaymentJournal(join(sandbox,"payment-journal"));
  let stopped = false, offset = 0;
  process.once("SIGINT", () => {stopped = true;});
  process.once("SIGTERM", () => {stopped = true;});
  try {
    await bot.init(); // grammY uses only https://api.telegram.org/bot<TOKEN>/test/...
    console.log("Тестовая среда Telegram: бот запущен. Ctrl+C — остановить.");
    while (!stopped) {
      try {
        await replayJournal(journal, r => storage.paymentApply(r.userId,r.orderId,r.currency,r.amount,r.chargeId));
        await reconcileStarHistory((o,l) => bot.api.getStarTransactions({offset:o,limit:l}), storage);
        const updates = await bot.api.getUpdates({offset,timeout:25});
        offset = await processBatch(updates,offset,journal,async update => { try { await bot.handleUpdate(update); } catch (_) { console.error("TEST_UPDATE_FAILED"); } }, (user,charge,amount,currency,order) => storage.refundConfirm(user,charge,amount,currency,order));
      } catch (_) { console.error("TEST_SYNC_UNAVAILABLE"); await new Promise(resolve => setTimeout(resolve,3000)); }
    }
  } finally { await storage.close(); }
}
main().catch((error: unknown) => {
  const failure = error as {name?: string; error_code?: number};
  if (failure?.name === "GrammyError" && failure.error_code === 401) console.error("Тестовый Telegram отклонил данные бота (401). Проверьте токен бота, созданного через @BotFather в Test Server.");
  else console.error("Тестовый запуск остановлен: проверьте тестовые настройки, отдельный токен и безопасные пути.");
  process.exitCode = 1;
});
