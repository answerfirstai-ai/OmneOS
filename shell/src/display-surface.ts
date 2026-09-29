/** The shell page a future Wayland host maps as the desktop layer. */

export const DESKTOP_SURFACE_URI = "http://127.0.0.1:4173/?surface=desktop";

export function desktopSurfaceUrl(shellUrl: string): string {
  const url = new URL(shellUrl);
  url.searchParams.set("surface", "desktop");
  return url.toString();
}
