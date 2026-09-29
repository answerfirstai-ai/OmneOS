/** How much internal state the desktop shows. */

export type DetailLevel = "normal" | "inspect" | "debug";

export function cycleDetail(level: DetailLevel): DetailLevel {
  if (level === "normal") {
    return "inspect";
  }
  if (level === "inspect") {
    return "debug";
  }
  return "normal";
}

export function detailLabel(level: DetailLevel): string {
  if (level === "inspect") {
    return "Inspect";
  }
  if (level === "debug") {
    return "Debug";
  }
  return "Normal";
}
