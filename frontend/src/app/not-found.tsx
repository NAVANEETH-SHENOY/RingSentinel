import Link from "next/link";

export default function NotFound() {
  return (
    <div className="state">
      <h3>Page not found</h3>
      <p className="muted">
        Go to the <Link href="/">review queue</Link>.
      </p>
    </div>
  );
}
