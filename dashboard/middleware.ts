import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "prospectiq-session";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow login page and auth API routes through
  if (pathname.startsWith("/login") || pathname.startsWith("/api/auth")) {
    return NextResponse.next();
  }

  const session = request.cookies.get(SESSION_COOKIE);
  const expected = process.env.DASHBOARD_SESSION_SECRET;

  if (!session || !expected || session.value !== expected) {
    const url = new URL("/login", request.url);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.png$|.*\\.svg$|.*\\.ico$).*)",
  ],
};
