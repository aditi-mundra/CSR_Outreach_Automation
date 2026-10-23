// "₹2.50 crore" / "₹4.20 lakh" - how CSR amounts are discussed in India.
export function formatInr(amount) {
  if (amount === null || amount === undefined) return null;
  if (amount >= 1e7) return `₹${(amount / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 2 })} crore`;
  if (amount >= 1e5) return `₹${(amount / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 2 })} lakh`;
  return `₹${amount.toLocaleString("en-IN")}`;
}

export function displayHost(url) {
  if (!url) return "";
  return url.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/$/, "");
}
