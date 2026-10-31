import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import { createInterface } from "readline";
import { Language, isLanguage } from "./translations";

export interface Subscription { started_at: number; expires_at: number }
export interface VPNResponse { status: string; address?: string; server_public_key?: string; endpoint?: string }
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
    this.process.stderr.on("data", () => { /* Не выводим возможные чувствительные данные. */ });
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
  close(): Promise<void> {
    if (this.stopped) return Promise.resolve();
    const closed = new Promise<void>(resolve => this.process.once("close", () => resolve()));
    this.process.stdin.end();
    return closed;
  }
}
