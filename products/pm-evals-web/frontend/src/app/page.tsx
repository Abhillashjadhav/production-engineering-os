import { Explainer } from "@/lib/explainer";

// Screen S-1 shell (journey step J-1): what the product does, in plain words.
// The upload journey (J-2..J-5) lands on this screen in the next PR.
export default function HomePage() {
  return (
    <main>
      <Explainer />
    </main>
  );
}
