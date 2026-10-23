import { useEffect, useState } from "react";
import { getEmailMeta } from "../api/client";

// Status / classification / email-type labels come from the backend
// (app/mail/states.py) so both sides use one vocabulary. Fetched once.
let cached = null;

export function useEmailMeta() {
  const [meta, setMeta] = useState(null);
  useEffect(() => {
    let alive = true;
    cached = cached ?? getEmailMeta().catch(() => null);
    cached.then((value) => {
      if (alive) setMeta(value);
    });
    return () => {
      alive = false;
    };
  }, []);
  return meta;
}

export function formatDateTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
