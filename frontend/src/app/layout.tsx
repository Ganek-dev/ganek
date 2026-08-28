import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";

import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";

import "./globals.css";

import { publicBaseUrl } from "@/lib/site";

export const metadata: Metadata = {
  // absolute URLs for OG/twitter images and the sitemap's canonical origin
  metadataBase: new URL(publicBaseUrl()),
  title: "Ganek",
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
