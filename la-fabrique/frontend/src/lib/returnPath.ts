const blockedPaths = new Set(['/login', '/register', '/companies/select'])

export function safeReturnPath(from: string | null | undefined, fallback = '/'): string {
  if (
    !from ||
    !from.startsWith('/') ||
    from[1] === '/' ||
    from[1] === '\\' ||
    /[\\\u0000-\u001f\u007f]/.test(from) ||
    /%(?:0[0-9a-f]|1[0-9a-f]|7f)/i.test(from)
  ) {
    return fallback
  }

  const path = from.split(/[?#]/, 1)[0]
  return blockedPaths.has(path) ? fallback : from
}
