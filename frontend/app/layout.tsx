import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Virtual Office & Trading Hub",
  description: "Kantor virtual multi-agen: Departemen IT dan Intraday Arena (Bull, Bear, Risk).",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#070c18" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
