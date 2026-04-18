export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html>
      <body className="bg-zinc-950 text-white">
        {children}
      </body>
    </html>
  );
}
