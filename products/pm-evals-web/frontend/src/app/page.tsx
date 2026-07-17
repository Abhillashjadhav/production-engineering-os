import { UploadForm } from "@/components/upload-form";
import { Explainer } from "@/lib/explainer";

// Screen S-1: the explainer (J-1) plus the upload-and-compare journey
// (J-2..J-5, J-9). The evidence dashboard (S-2) renders below in PR 8.
export default function HomePage() {
  return (
    <main>
      <Explainer />
      <UploadForm />
    </main>
  );
}
