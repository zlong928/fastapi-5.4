import { DocumentUploader } from "@/components/DocumentUploader";

export function UploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Ingestion</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Upload Documents</h1>
        <p className="mt-2 text-sm text-slate-500">
          Add PDF, Markdown, TXT, or image files to your private second brain. Processing status appears after each upload.
        </p>
      </div>
      <DocumentUploader />
    </div>
  );
}
