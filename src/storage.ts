import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import { createInterface } from "readline";
import { Language, isLanguage } from "./translations";

export interface Subscription { started_at: number; expires_at: number }
export interface SubscriptionView { subscription: Subscription | null; source: "test" | "paid" | "mixed" | "unknown"; vpn: "none" | "unknown" | "allowed" | "revoked" }
export interface VPNResponse { status: string; address?: string; server_public_key?: string; endpoint?: string }
export interface VPNAlert { user_id: number; action: string; code: string; active: number; occurred_at: number; resolved_at: number | null; version: number; phase: "failure" | "resolved" }
type Pending = { resolve: (value: any) => void; reject: (error: Error) => void };

// Один процесс, одна очередь запросов: Python отвечает в том же порядке.
export class Storage {
  private process: ChildProcessWithoutNullStreams;
  private pending: Pending[] = [];
  private stopped = false;

  constructor(cwd = process.cwd()) {
    const env: NodeJS.ProcessEnv = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONDONTWRITEBYTECODE: "1" };
    delete env.BOT_TOKEN;
    this.process = spawn("python", ["-u", "storage/service.py"], { env, cwd });
    this.process.stderr.on("data", data => { if (String(data).includes("VPN_RECONCILE_SCAN_ERROR")) console.error("VPN_RECONCILE_SCAN_ERROR"); });
    this.process.on("error", () => this.fail());
    this.process.on("exit", () => this.fail());
    this.process.stdin.on("error", () => this.fail());
    createInterface({ input: this.process.stdout }).on("line", line => {
      const request = this.pending.shift();
      if (!request) return;
      try {
        const response = JSON.parse(line);
        if (!response.ok) throw new Error();
        request.resolve(response);
      } catch (_) { request.reject(new Error("Storage request failed")); }
    });
  }

  private fail(): void {
    this.stopped = true;
    this.pending.splice(0).forEach(request => request.reject(new Error("Storage unavailable")));
  }

  private request(command: object): Promise<any> {
    if (this.stopped) return Promise.reject(new Error("Storage unavailable"));
    return new Promise((resolve, reject) => {
      this.pending.push({ resolve, reject });
      this.process.stdin.write(JSON.stringify(command) + "\n");
    });
  }

  async get(userId: number): Promise<Language | null> {
    const response = await this.request({ action: "get", user_id: userId });
    if (response.language !== null && !isLanguage(response.language)) throw new Error("Invalid storage response");
    return response.language;
  }
  async set(userId: number, language: Language): Promise<void> {
    const response = await this.request({ action: "set", user_id: userId, language });
    if (response.language !== language) throw new Error("Invalid storage response");
  }
  async register(userId: number): Promise<void> {
    const response = await this.request({ action: "register", user_id: userId });
    if (response.value !== true) throw new Error("Invalid storage response");
  }
  private subscriptionResponse(value: any): Subscription | null {
    if (value === null) return null;
    if (!value || !Number.isSafeInteger(value.started_at) || !Number.isSafeInteger(value.expires_at) || value.started_at < 0 || value.expires_at < value.started_at || value.expires_at > 253402300799) throw new Error("Invalid storage response");
    return { started_at: value.started_at, expires_at: value.expires_at };
  }
  async subscription(userId: number): Promise<Subscription | null> {
    const response = await this.request({ action: "subscription", user_id: userId });
    return this.subscriptionResponse(response.value);
  }
  async subscriptionView(userId: number): Promise<SubscriptionView> {
    const value = (await this.request({action: "subscription_view", user_id: userId})).value;
    if (!value || !["test", "paid", "mixed", "unknown"].includes(value.source) || !["none", "unknown", "allowed", "revoked"].includes(value.vpn)) throw new Error("Invalid storage response");
    return {subscription: this.subscriptionResponse(value.subscription), source: value.source, vpn: value.vpn};
  }
  async grant(userId: number, days: number): Promise<Subscription | null> {
    const response = await this.request({ action: "grant", user_id: userId, days });
    return this.subscriptionResponse(response.value);
  }
  async vpnRequest(userId: number, publicKey: string): Promise<VPNResponse> {
    const response = await this.request({ action: "vpn_request", user_id: userId, public_key: publicKey });
    const value = response.value;
    if (!value || !["invalid_key", "inactive", "device_exists", "key_in_use", "ip_in_use", "unavailable", "unconfirmed", "confirmed"].includes(value.status)) throw new Error("Invalid storage response");
    if (value.status === "confirmed" && (typeof value.address !== "string" || typeof value.server_public_key !== "string" || typeof value.endpoint !== "string")) throw new Error("Invalid storage response");
    return value;
  }
  async alertsDue(): Promise<VPNAlert[]> {
    const value = (await this.request({action: "alerts_due"})).value;
    if (!Array.isArray(value)) throw new Error("Invalid alerts response");
    return value;
  }
  async alertsAck(event: VPNAlert): Promise<void> {
    const value = (await this.request({action: "alerts_ack", event})).value;
    if (value !== true) throw new Error("Invalid alert acknowledgement");
  }
  async paymentOrder(userId: number, planId: string, amount: number): Promise<any> {
    return (await this.request({action: "payment_order", user_id: userId, plan_id: planId, amount})).value;
  }
  async refundPrepare(adminId: number, userId: number, chargeId: string): Promise<{status: string; recalc_status: string}> {
    return (await this.request({action: "refund_prepare", admin_id: adminId, user_id: userId, charge_id: chargeId})).value;
  }
  async refundBegin(adminId: number, userId: number, chargeId: string): Promise<{status: string; ready?: boolean; amount?: number; currency?: string}> {
    return (await this.request({action: "refund_begin", admin_id: adminId, user_id: userId, charge_id: chargeId})).value;
  }
  async refundConfirm(userId: number, chargeId: string, amount: number, currency: string, orderId?: string): Promise<string> {
    const value = (await this.request({action: "refund_confirm", user_id: userId, charge_id: chargeId, amount, currency, order_id: orderId})).value;
    if (!["applied", "manual_review", "review"].includes(value)) throw new Error("Invalid refund confirmation");
    return value;
  }
  async refundReject(adminId: number, userId: number, chargeId: string): Promise<boolean> {
    return (await this.request({action: "refund_reject", admin_id: adminId, user_id: userId, charge_id: chargeId})).value === true;
  }
  async paymentValidate(userId: number, orderId: string, currency: string, amount: number): Promise<boolean> {
    return (await this.request({action: "payment_validate", user_id: userId, order_id: orderId, currency, amount})).value === true;
  }
  async paymentApply(userId: number, orderId: string, currency: string, amount: number, chargeId: string): Promise<any> {
    return (await this.request({action: "payment_apply", user_id: userId, order_id: orderId, currency, amount, charge_id: chargeId})).value;
  }
  async starObserve(transaction: object): Promise<void> { await this.request({action: "star_observe", transaction}); }
  async starFinalize(): Promise<void> { await this.request({action: "star_finalize"}); }
  close(): Promise<void> {
    if (this.stopped) return Promise.resolve();
    const closed = new Promise<void>(resolve => this.process.once("close", () => resolve()));
    this.process.stdin.end();
    return closed;
  }
}
