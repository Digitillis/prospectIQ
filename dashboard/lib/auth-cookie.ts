/**
 * Helper to sync Supabase session from browser storage to cookies
 * so the middleware can read it
 */
export function setAuthCookie(accessToken: string, refreshToken: string) {
  // Set auth cookie that middleware can read
  const maxAge = 365 * 24 * 60 * 60; // 1 year

  document.cookie = `sb-access-token=${accessToken}; path=/; max-age=${maxAge}; samesite=lax`;
  document.cookie = `sb-refresh-token=${refreshToken}; path=/; max-age=${maxAge}; samesite=lax; httponly`;

  console.log("🍪 Auth cookies set for middleware");
}

export function clearAuthCookies() {
  document.cookie = "sb-access-token=; path=/; max-age=0";
  document.cookie = "sb-refresh-token=; path=/; max-age=0";
  console.log("🍪 Auth cookies cleared");
}
