import { Link } from "react-router-dom";
import { Card, EmptyState } from "@/components/ui";

export function NotFoundPage() {
  return (
    <main className="px-10 py-8">
      <Card>
        <EmptyState
          title="Halaman tidak ditemukan"
          description="Alamat ini tidak ada di dashboard QA Agent."
          action={
            <Link to="/" className="text-sm text-accent">
              Kembali ke Dashboard
            </Link>
          }
        />
      </Card>
    </main>
  );
}
