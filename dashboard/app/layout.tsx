"use client";

import { Inter } from "next/font/google";
import { usePathname, useRouter } from "next/navigation";
import { LogOut, Moon, Sun } from "lucide-react";
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
      <html lang="en" suppressHydrationWarning>
        <head>
          <script dangerouslySetInnerHTML={{ __html: `
            try {
              if (localStorage.getItem('prospectiq-theme') === 'dark' ||
                  (!localStorage.getItem('prospectiq-theme') &&
                   window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.classList.add('dark');
              }
            } catch(e) {}
          `}} />
        </head>
        <body className={inter.className}>{children}</body>
      </html>
    );
  }

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `
          try {
            if (localStorage.getItem('prospectiq-theme') === 'dark' ||
                (!localStorage.getItem('prospectiq-theme') &&
                 window.matchMedia('(prefers-color-scheme: dark)').matches)) {
              document.documentElement.classList.add('dark');
            }
          } catch(e) {}
        `}} />
      </head>
      <body className={inter.className}>
        <div className="flex h-screen overflow-hidden bg-white dark:bg-gray-950">
          <Sidebar />
          <SearchModal />
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Top bar */}
            <header className="flex h-14 items-center justify-between border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-6">
              <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">ProspectIQ</h1>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    const isDark = document.documentElement.classList.toggle('dark');
                    localStorage.setItem('prospectiq-theme', isDark ? 'dark' : 'light');
                  }}
                  className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-gray-500 dark:text-gray-400 transition-colors hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100"
                  title="Toggle dark mode"
                >
                  <Moon className="h-3.5 w-3.5 hidden dark:block" />
                  <Sun className="h-3.5 w-3.5 block dark:hidden" />
                </button>
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-gray-500 dark:text-gray-400 transition-colors hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100"
                  title="Sign out"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  Sign out
                </button>
              </div>
            </header>
            {/* Main content */}
            <main className="flex-1 overflow-y-auto bg-white dark:bg-gray-950 p-6">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
