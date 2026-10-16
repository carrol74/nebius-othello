export function sameOrigin(origin: string | null, host: string | null, protocol: string): boolean {
  if (!origin || !host || !["http:", "https:"].includes(protocol)) return false;
  try {
    const source = new URL(origin);
    const destination = new URL(`${protocol}//${host}`);
    return source.origin === origin
      && !destination.username && !destination.password
      && destination.pathname === "/" && !destination.search && !destination.hash
      && source.origin === destination.origin;
  } catch {
    return false;
  }
}
