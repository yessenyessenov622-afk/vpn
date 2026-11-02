import { createHash, randomBytes } from "crypto";
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "fs";
import { join, resolve } from "path";
import { spawnSync } from "child_process";

export interface PaymentReceipt { userId: number; orderId: string; currency: string; amount: number; chargeId: string }
export class PaymentJournal {
  constructor(private directory: string) {}
  private windowsAcl(action: "ensure" | "check-file", target: string): void {
    const script = resolve(__dirname, "../storage/journal_acl.ps1");
    const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-File", script, "-Action", action, "-Target", resolve(target)], {stdio: "ignore", windowsHide: true});
    if (result.error || result.status !== 0) throw new Error("payment journal ACL unavailable or unsafe");
  }
  private ensureDirectory(): void {
    if (process.platform === "win32") this.windowsAcl("ensure", this.directory);
    else {
      mkdirSync(this.directory, {recursive: true, mode: 0o700});
      const info = lstatSync(this.directory);
      if (!info.isDirectory() || info.isSymbolicLink() || (info.mode & 0o077) !== 0 || (typeof process.getuid === "function" && info.uid !== process.getuid())) throw new Error("payment journal directory unsafe");
    }
  }
  private checkFile(path: string): void {
    if (process.platform === "win32") this.windowsAcl("check-file", path);
    else {
      const info = lstatSync(path);
      if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o077) !== 0 || (typeof process.getuid === "function" && info.uid !== process.getuid())) throw new Error("payment journal file unsafe");
    }
  }
  private filename(chargeId: string): string { return join(this.directory, createHash("sha256").update(chargeId).digest("hex") + ".json"); }
  private syncDirectory(): void {
    if (process.platform === "win32") return; // Windows lacks portable directory fsync.
    const fd = openSync(this.directory, "r"); try { fsyncSync(fd); } finally { closeSync(fd); }
  }
  private validate(r: PaymentReceipt): void {
    if (!Number.isSafeInteger(r.userId) || r.userId <= 0 || !Number.isSafeInteger(r.amount) || r.amount <= 0 || r.currency !== "XTR" || typeof r.orderId !== "string" || r.orderId.length < 1 || r.orderId.length > 128 || typeof r.chargeId !== "string" || r.chargeId.length < 1 || r.chargeId.length > 255) throw new Error("invalid payment receipt");
  }
  record(receipt: PaymentReceipt): void {
    this.validate(receipt);
    this.ensureDirectory();
    const path = this.filename(receipt.chargeId);
    const serialized = JSON.stringify(receipt);
    if (existsSync(path)) {
      this.checkFile(path);
      if (readFileSync(path, "utf8") !== serialized) throw new Error("conflicting payment receipt");
      const existing = openSync(path, "r+"); try { fsyncSync(existing); } finally { closeSync(existing); }
      this.syncDirectory();
      return;
    }
    const temporary = path + "." + randomBytes(12).toString("hex") + ".tmp";
    const fd = openSync(temporary, "wx", 0o600);
    try { this.checkFile(temporary); writeFileSync(fd, serialized, "utf8"); fsyncSync(fd); } finally { closeSync(fd); }
    renameSync(temporary, path);
    this.syncDirectory();
  }
  pending(): PaymentReceipt[] {
    if (!existsSync(this.directory)) return [];
    this.ensureDirectory();
    return readdirSync(this.directory).filter(n => /^[a-f0-9]{64}\.json$/.test(n)).map(n => {
      const file = join(this.directory, n); this.checkFile(file);
      const data = JSON.parse(readFileSync(file, "utf8")) as PaymentReceipt;
      this.validate(data);
      if (this.filename(data.chargeId) !== join(this.directory, n)) throw new Error("invalid journal entry");
      return data;
    });
  }
  remove(receipt: PaymentReceipt): void { this.ensureDirectory(); const file = this.filename(receipt.chargeId); this.checkFile(file); unlinkSync(file); this.syncDirectory(); }
}
