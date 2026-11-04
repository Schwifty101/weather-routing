export function formatDuration(seconds: number): string {
  const total = Math.round(seconds / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export function formatMiles(miles: number): string {
  return miles >= 100 ? Math.round(miles).toLocaleString() : miles.toFixed(1);
}

const dayTime = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
const dayTimeLong = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export const formatEta = (iso: string): string => dayTime.format(new Date(iso));
export const formatDateTime = (iso: string): string => dayTimeLong.format(new Date(iso));

/** `<input type="datetime-local">` wants local time as YYYY-MM-DDTHH:mm. */
export function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Next whole hour from `now`, a sensible default departure. */
export function nextHour(now = new Date()): Date {
  const d = new Date(now);
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return d;
}

export const addHours = (iso: string, hours: number): string => new Date(new Date(iso).getTime() + hours * 3600_000).toISOString();
