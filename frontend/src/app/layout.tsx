import type { Metadata } from "next";

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
    <html lang="en">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
