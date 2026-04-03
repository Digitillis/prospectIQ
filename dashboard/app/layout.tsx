"use client";

export const dynamic = "force-dynamic";

import { Inter } from "next/font/google";
import { usePathname, useRouter } from "next/navigation";
import { LogOut, Moon, Sun, User } from "lucide-react";
import { Sidebar } from "./sidebar";
import { SearchModal } from "./search-modal";
import { AuthProvider, useAuth } from "@/lib/auth-provider";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

function TopBar() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push("/login");
    router.refresh();
  };

  return (
    <header className="flex h-14 items-center justify-between border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-6">
      <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wide">
        ProspectIQ
      </h1>
      <div className="flex items-center gap-3">
        {user && (
          <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
            <User className="h-3.5 w-3.5" />
            <span>{user.name}</span>
          </div>
        )}
        <button
          onClick={() => {
            const isDark = document.documentElement.classList.toggle("dark");
            localStorage.setItem("prospectiq-theme", isDark ? "dark" : "light");
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
  );
}

function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLogin = pathname === "/login";

  if (isLogin) {
    return <body className={inter.className}>{children}</body>;
  }

  return (
    <body className={inter.className}>
      <div className="flex h-screen overflow-hidden bg-white dark:bg-gray-950">
        <Sidebar />
        <SearchModal />
        <div className="flex flex-1 flex-col overflow-hidden">
          <TopBar />
          <main className="flex-1 overflow-y-auto bg-white dark:bg-gray-950 p-6">
            {children}
          </main>
        </div>
      </div>
    </body>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                if (localStorage.getItem('prospectiq-theme') === 'dark' ||
                    (!localStorage.getItem('prospectiq-theme') &&
                     window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                  document.documentElement.classList.add('dark');
                }
              } catch(e) {}
            `,
          }}
        />
      </head>
      <AuthProvider>
        <AppShell>{children}</AppShell>
      </AuthProvider>
    </html>
  );
}
