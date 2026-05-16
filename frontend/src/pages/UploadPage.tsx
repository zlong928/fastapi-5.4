import { FileUploader } from "@/components/FileUploader";

export function UploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Advanced tools</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Basic File Parser</h1>
        <p className="mt-2 text-sm text-slate-500">
          Use this for simple file splitting/extraction. For full document parsing, OCR, search, and knowledge graph extraction, use Documents.
        </p>
      </div>
      <FileUploader />
    </div>
  );
}
