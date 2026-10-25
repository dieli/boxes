/** A part name usable as a file name. */
export function safeName(s: string): string {
  return s.trim().replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "") || "part";
}
