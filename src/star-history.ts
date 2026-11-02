type HistoryStore = { starObserve(t: object): Promise<void>; starFinalize(): Promise<void> };
type Page = { transactions: any[] };
type Observation = { id: string; direction: "incoming" | "outgoing" | "unknown"; user_id: number | null; order_id: string | null; amount: number; date: number; refund_verified?: boolean };

function normalize(t: any): Observation[] {
  if (!t || typeof t.id !== "string" || !t.id || !Number.isSafeInteger(t.amount) || !Number.isSafeInteger(t.date)) throw new Error("invalid history item");
  const result: Observation[] = [];
  if (t.source) {
    const s = t.source;
    const valid = s.type === "user" && s.transaction_type === "invoice_payment" && !s.subscription_period && !t.nanostar_amount;
    result.push({id: t.id, direction: "incoming", user_id: Number.isSafeInteger(s.user?.id) ? s.user.id : null, order_id: valid && typeof s.invoice_payload === "string" ? s.invoice_payload : null, amount: t.amount, date: t.date});
  }
  if (t.receiver) {
    const r = t.receiver;
    const valid = r.type === "user" && r.transaction_type === "invoice_payment" && !r.subscription_period && !t.nanostar_amount;
    result.push({id: t.id, direction: valid ? "outgoing" : "unknown", user_id: valid && Number.isSafeInteger(r.user?.id) ? r.user.id : null, order_id: null, amount: t.amount, date: t.date, refund_verified: valid});
  }
  if (!result.length) result.push({id: t.id, direction: "unknown", user_id: null, order_id: null, amount: t.amount, date: t.date});
  return result;
}

// Always restart at offset zero. Persist every observation before fetching the next page.
// Two matching full scans are required before processing; continuous changes fail closed.
export async function reconcileStarHistory(fetchPage: (offset: number, limit: number) => Promise<Page>, store: HistoryStore, pageSize = 100): Promise<void> {
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new Error("invalid page size");
  let previous: string | null = null;
  for (let pass = 0; pass < 5; pass++) {
    const entries = new Map<string, string>();
    let offset = 0;
    for (let pageNumber = 0; ; pageNumber++) {
      if (pageNumber >= 10000) throw new Error("history too large");
      const page = await fetchPage(offset, pageSize);
      if (!page || !Array.isArray(page.transactions) || page.transactions.length > pageSize) throw new Error("invalid history page");
      for (const item of page.transactions) for (const entry of normalize(item)) {
        await store.starObserve(entry);
        const id = entry.direction + ":" + entry.id;
        const value = JSON.stringify(entry);
        if (entries.has(id) && entries.get(id) !== value) throw new Error("conflicting history items");
        entries.set(id, value);
      }
      if (page.transactions.length < pageSize) break;
      offset += page.transactions.length;
    }
    const signature = JSON.stringify([...entries.entries()].sort((a,b) => a[0].localeCompare(b[0])));
    if (signature === previous) { await store.starFinalize(); return; }
    previous = signature;
  }
  throw new Error("history did not stabilize");
}
