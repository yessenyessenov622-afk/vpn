import { VPNAlert } from "./storage";

type AlertStorage = { alertsDue(): Promise<VPNAlert[]>; alertsAck(event: VPNAlert): Promise<void> };
type Send = (text: string) => Promise<unknown>;
const actions: Record<string, string> = {check: "проверка устройства", revoke: "отзыв доступа", restore: "восстановление доступа", enable: "выдача доступа", scan: "фоновая проверка"};
const codes = new Set(["controller_error", "unconfirmed", "conflict", "scan_error"]);
const reasons: Record<string, string> = {controller_error: "Контроллер недоступен или отклонил запрос", unconfirmed: "Сервер не подтвердил операцию", conflict: "Обнаружен конфликт ключа или адреса", scan_error: "Фоновая проверка завершилась с ошибкой"};

export function formatAlert(event: VPNAlert): string {
  if (!(event.action in actions) || !codes.has(event.code) || !Number.isSafeInteger(event.user_id) || event.user_id < 0 || !["failure", "resolved"].includes(event.phase)) throw new Error("Invalid alert");
  const when = event.phase === "resolved" ? event.resolved_at : event.occurred_at;
  if (typeof when !== "number" || !Number.isFinite(when)) throw new Error("Invalid alert time");
  const date = new Date(when * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC");
  return `${event.phase === "resolved" ? "✅ Проблема устранена" : "⚠️ Ошибка VPN"}\nДействие: ${actions[event.action]}\nПричина: ${reasons[event.code]}\nКод: ${event.code}\nВремя: ${date}${event.user_id ? `\nID пользователя: ${event.user_id}` : ""}`;
}

export class AlertDispatcher {
  private unavailableSince: number | null = null;
  private lastUnavailableSent: number | null = null;
  constructor(private storage: AlertStorage, private send: Send, private now: () => number = () => Date.now()) {}

  async run(): Promise<void> {
    let events: VPNAlert[];
    try { events = await this.storage.alertsDue(); }
    catch (_) {
      const now = this.now();
      if (this.unavailableSince === null) this.unavailableSince = now;
      if (this.lastUnavailableSent === null || now - this.lastUnavailableSent >= 3600000) {
        try { await this.send(`⚠️ Ошибка VPN\nДействие: фоновая проверка\nКод: storage_unavailable\nВремя: ${new Date(this.unavailableSince).toISOString()} (UTC)`); this.lastUnavailableSent = now; }
        catch (_) { console.error("VPN_ALERT_DELIVERY_FAILED"); }
      }
      console.error("VPN_ALERT_STORAGE_UNAVAILABLE");
      return;
    }
    if (this.unavailableSince !== null) {
      if (this.lastUnavailableSent !== null) {
        try { await this.send(`✅ Проблема устранена\nДействие: фоновая проверка\nКод: storage_unavailable\nВремя: ${new Date(this.now()).toISOString()} (UTC)`); }
        catch (_) { console.error("VPN_ALERT_DELIVERY_FAILED"); return; }
      }
      this.unavailableSince = null; this.lastUnavailableSent = null;
    }
    for (const event of events) {
      try { await this.send(formatAlert(event)); await this.storage.alertsAck(event); }
      catch (_) { console.error("VPN_ALERT_DELIVERY_FAILED"); }
    }
  }
}
