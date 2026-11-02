type RefundStore = {
  refundBegin(adminId: number, userId: number, chargeId: string): Promise<{status: string; ready?: boolean; amount?: number; currency?: string}>;
  refundConfirm(userId: number, chargeId: string, amount: number, currency: string): Promise<string>;
  refundReject(adminId: number, userId: number, chargeId: string): Promise<boolean>;
};

// Production calls this only behind the hard-coded disabled gate in handlers.ts.
// Tests inject a fake Telegram API. No automatic retries are ever attempted.
export async function executeRefund(store: RefundStore, admin: number, user: number, charge: string, send: (user: number, charge: string) => Promise<boolean>): Promise<string> {
  const intent = await store.refundBegin(admin, user, charge);
  if (!intent.ready) return intent.status;
  if (!Number.isSafeInteger(intent.amount) || !intent.amount || intent.currency !== "XTR") return "uncertain";
  let answer: boolean;
  try { answer = await send(user, charge); } catch (_) { return "uncertain"; }
  if (answer === false) {
    try { return await store.refundReject(admin, user, charge) ? "rejected" : "uncertain"; }
    catch (_) { return "uncertain"; }
  }
  if (answer !== true) return "uncertain";
  try { return await store.refundConfirm(user, charge, intent.amount!, intent.currency); }
  catch (_) { return "uncertain"; }
}
