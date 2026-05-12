import { DocumentUploader } from "@/components/DocumentUploader";

export function UploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Upload</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Upload Documents</h1>
        <p className="mt-2 text-sm text-slate-500">
          Upload PDF, Markdown, text, or image files to your knowledge base. They will be automatically parsed and indexed.
        </p>
      </div>
      <DocumentUploader />
    </div>
  );
}
