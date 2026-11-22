import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-10">
      <div className="mb-6 text-center">
        <div className="text-2xl font-semibold">UEOS</div>
        <p className="mt-1 text-sm text-muted">Universal Enterprise Operating System</p>
      </div>
      {children}
    </main>
  );
}
