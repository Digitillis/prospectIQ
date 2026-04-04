export async function GET() {
  try {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    return Response.json({
      supabaseUrl: supabaseUrl ? "✓ Set" : "✗ Missing",
      supabaseAnonKey: supabaseAnonKey ? "✓ Set" : "✗ Missing",
      timestamp: new Date().toISOString(),
    });
  } catch (e) {
    return Response.json({
      error: String(e),
    }, { status: 500 });
  }
}
