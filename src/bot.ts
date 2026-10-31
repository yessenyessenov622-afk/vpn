import "dotenv/config";
import { Storage } from "./storage";
import { createBot, parseAdminId } from "./handlers";

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
const stop = () => { bot.stop(); storage.close(); };
process.once("SIGINT", stop);
process.once("SIGTERM", stop);
console.log("Бот запускается. Для остановки нажмите Ctrl+C.");
bot.start().catch(() => {
  console.error("Не удалось запустить бота. Проверьте токен и подключение к Telegram.");
  storage.close();
  process.exitCode = 1;
});
