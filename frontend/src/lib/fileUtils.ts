export const ACCEPTED_KNOWLEDGE_FILES = [
  ".pdf",
  ".md",
  ".markdown",
  ".txt",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".epub",
  ".docx",
  ".mp4",
  ".mov",
  ".m4v",
  ".webm",
  ".avi",
  ".mkv",
  "video/mp4",
  "video/quicktime",
  "video/x-m4v",
  "video/webm",
  "video/x-msvideo",
  "video/x-matroska"
].join(",");

const ACCEPTED_EXTENSIONS = new Set(["pdf", "md", "markdown", "txt", "png", "jpg", "jpeg", "webp", "epub", "docx", "mp4", "mov", "m4v", "webm", "avi", "mkv"]);
const ACCEPTED_MIME_PREFIXES = ["image/", "video/"];

export function isAcceptedKnowledgeFile(file: File) {
  const extension = file.name.includes(".") ? file.name.split(".").pop()?.toLowerCase() : undefined;
  if (extension && ACCEPTED_EXTENSIONS.has(extension)) return true;
  return ACCEPTED_MIME_PREFIXES.some((prefix) => file.type.startsWith(prefix));
}
