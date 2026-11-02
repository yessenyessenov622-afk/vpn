import { PaymentJournal, PaymentReceipt } from "./payment-journal";

export function receiptFromUpdate(update: any): PaymentReceipt | null {
  const message = update?.message;
  const payment = message?.successful_payment;
  if (!payment) return null;
  return {userId: message.from?.id, orderId: payment.invoice_payload, currency: payment.currency, amount: payment.total_amount, chargeId: payment.telegram_payment_charge_id};
}

// Advance the Telegram offset only after the confirmed payment is on disk.
export async function processBatch(updates: any[], offset: number, journal: PaymentJournal, handle: (update: any) => Promise<void>, confirmRefund?: (userId: number, charge: string, amount: number, currency: string, order: string) => Promise<string>): Promise<number> {
  for (const update of updates) {
    const receipt = receiptFromUpdate(update);
    if (receipt) journal.record(receipt);
    const message = update?.message;
    const refund = message?.refunded_payment;
    if (refund) {
      const user = message.chat?.id;
      if (message.chat?.type !== "private" || !Number.isSafeInteger(user) || user <= 0 || user > 2 ** 52 || refund.currency !== "XTR" || !Number.isSafeInteger(refund.total_amount) || refund.total_amount <= 0 || typeof refund.invoice_payload !== "string" || !refund.invoice_payload || typeof refund.telegram_payment_charge_id !== "string" || !refund.telegram_payment_charge_id || !confirmRefund) throw new Error("refund update requires manual investigation");
      const result = await confirmRefund(user, refund.telegram_payment_charge_id, refund.total_amount, refund.currency, refund.invoice_payload);
      if (!["applied", "manual_review", "review"].includes(result)) throw new Error("refund persistence unconfirmed");
    }
    await handle(update);
    offset = update.update_id + 1;
  }
  return offset;
}

export async function replayJournal(journal: PaymentJournal, apply: (r: PaymentReceipt) => Promise<any>): Promise<void> {
  for (const receipt of journal.pending()) {
    const result = await apply(receipt);
    if (["paid", "duplicate", "pending"].includes(result?.status)) journal.remove(receipt);
    else throw new Error("payment transfer unconfirmed");
  }
}
