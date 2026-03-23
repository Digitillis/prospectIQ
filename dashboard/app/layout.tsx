"use client";

import { Inter } from "next/font/google";
import { usePathname, useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Sidebar } from "./sidebar";
import { SearchModal } from "./search-modal";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/login";

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  };

  if (isLogin) {
    return (
      <html lang="en">
        <body className={inter.className}>{children}</body>
      </html>
    );
  }

  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <SearchModal />
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Top bar */}
            <header className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-6">
              <h1 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">ProspectIQ</h1>
              <button
                onClick={handleLogout}
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900"
                title="Sign out"
              >
                <LogOut className="h-3.5 w-3.5" />
                Sign out
              </button>
            </header>
            {/* Main content */}
            <main className="flex-1 overflow-y-auto bg-white p-6">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
