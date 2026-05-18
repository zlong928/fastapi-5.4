export const APP_TIME_ZONE = "Asia/Shanghai";

export function formatChinaDateTime(value?: string | null) {
  if (!value) return "-";

  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: APP_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function formatChinaDate(value?: string | null) {
  if (!value) return "-";

  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: APP_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date(value));
}
