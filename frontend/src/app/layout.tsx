import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";

import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";

import "./globals.css";

export const metadata: Metadata = {
  title: "Vetd",
  description: "Open-source careers pages with built-in skill screening",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={GeistSans.variable}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
