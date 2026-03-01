import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const { password } = await req.json();

    const correctPassword = process.env.DASHBOARD_PASSWORD;
    const sessionSecret = process.env.DASHBOARD_SESSION_SECRET;

    if (!correctPassword || password !== correctPassword) {
      return NextResponse.json({ error: "Invalid password" }, { status: 401 });
    }

    const response = NextResponse.json({ ok: true });
    response.cookies.set("prospectiq-session", sessionSecret ?? "default-secret", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7, // 7 days
      path: "/",
    });
    return response;
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
}
