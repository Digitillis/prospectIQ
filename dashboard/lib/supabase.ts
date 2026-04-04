import { createClient as createSupabaseClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.error("Missing Supabase credentials:", {
    url: supabaseUrl ? "✓" : "✗ MISSING NEXT_PUBLIC_SUPABASE_URL",
    key: supabaseAnonKey ? "✓" : "✗ MISSING NEXT_PUBLIC_SUPABASE_ANON_KEY",
  });
}

// Singleton browser client — use for auth operations in client components
export const supabase = createSupabaseClient(supabaseUrl || "", supabaseAnonKey || "", {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storageKey: "prospectiq-auth",
    detectSessionInUrl: true,
    storage: typeof window !== "undefined" ? window.localStorage : undefined,
  },
});

// Named export for consistency with Supabase SSR patterns
export function createClient() {
  return supabase;
}
