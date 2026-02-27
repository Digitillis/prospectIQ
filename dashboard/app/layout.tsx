import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "./sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ProspectIQ",
  description: "AI-powered manufacturing sales intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Top bar */}
            <header className="flex h-14 items-center border-b border-gray-200 bg-white px-6">
              <h1 className="text-lg font-semibold text-gray-900">
                ProspectIQ
              </h1>
            </header>
            {/* Main content */}
            <main className="flex-1 overflow-y-auto bg-gray-50 p-6">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
