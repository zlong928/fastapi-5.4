import { FileUploader } from "@/components/FileUploader";

export function UploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Upload</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Upload PDF files</h1>
      </div>
      <FileUploader />
    </div>
  );
}
