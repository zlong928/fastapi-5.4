import { Badge } from "@/components/ui/badge";
import { DocumentStatus, ExtractionJob, ExtractionResult, PaperDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

export const DEFAULT_EXTRACTION_QUERY = "提取材料组成、实验分组、关键指标和主要结论";

export const FIELD_LABELS: Record<string, string> = {
  materials: "材料组成",
  experiment_groups: "实验分组",
  key_metrics: "关键指标",
  conclusion: "主要结论"
};

export const METRIC_ORDER = ["materials", "experiment_groups", "key_metrics", "conclusion"];

export const SOURCE_LABELS: Record<string, string> = {
  text: "正文",
  figure: "图片",
  table: "表格"
};

const PAPER_STATUS_LABELS: Record<string, string> = {
  pending: "等待解析",
  processing: "解析中",
  done: "已完成",
  completed: "已完成",
  failed: "失败",
  deleted: "已删除",
  uploaded: "已上传",
  parsing: "解析中",
  parsed: "已解析",
  extracting: "提取中"
};

const EXTRACTION_STATUS_LABELS: Record<string, string> = {
  pending: "等待执行",
  running: "提取中",
  done: "已完成",
  failed: "失败"
};

export function paperStatusLabel(status: DocumentStatus | string) {
  return PAPER_STATUS_LABELS[status] ?? status;
}

export function extractionStatusLabel(status: string) {
  return EXTRACTION_STATUS_LABELS[status] ?? status;
}

export function isPaperBusy(status?: string) {
  return status === "pending" || status === "processing" || status === "parsing" || status === "extracting";
}

export function isExtractionBusy(status?: string) {
  return status === "pending" || status === "running";
}

export function canExtractPaper(paper?: PaperDetail | null) {
  if (!paper) return false;
  return paper.status === "done" || paper.status === "parsed" || paper.figures.length > 0 || paper.tables.length > 0 || Boolean(paper.text_content?.trim());
}

export function shouldPollPaper(paper?: PaperDetail | null) {
  return isPaperBusy(paper?.status) || isExtractionBusy(paper?.latest_extraction_job?.status);
}

export function fieldLabel(fieldName: string) {
  return FIELD_LABELS[fieldName] ?? fieldName;
}

export function sourceLabel(sourceType: string) {
  return SOURCE_LABELS[sourceType] ?? sourceType;
}

export function confidencePercent(confidence?: number | null) {
  if (confidence === null || confidence === undefined) return null;
  return Math.round(confidence * 100);
}

export function resultMetricKeys(results: ExtractionResult[]) {
  const keys = Array.from(new Set(results.map((result) => result.field_name)));
  return keys.sort((left, right) => {
    const leftIndex = METRIC_ORDER.indexOf(left);
    const rightIndex = METRIC_ORDER.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) return fieldLabel(left).localeCompare(fieldLabel(right), "zh-CN");
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  });
}

export function resultsByMetric(results: ExtractionResult[]) {
  return results.reduce<Record<string, ExtractionResult[]>>((groups, result) => {
    groups[result.field_name] = groups[result.field_name] ?? [];
    groups[result.field_name].push(result);
    return groups;
  }, {});
}

export function resultSourceCounts(results: ExtractionResult[]) {
  return results.reduce<Record<string, number>>((counts, result) => {
    counts[result.source_type] = (counts[result.source_type] ?? 0) + 1;
    return counts;
  }, {});
}

export function PaperStatusBadge({ status }: { status: DocumentStatus | string }) {
  const failed = status === "failed";
  const busy = isPaperBusy(status);
  return (
    <Badge
      variant="outline"
      className={cn(
        "border-transparent",
        failed && "bg-red-50 text-red-700 ring-1 ring-red-200",
        busy && "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
        !failed && !busy && "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
      )}
    >
      {paperStatusLabel(status)}
    </Badge>
  );
}

export function ExtractionStatusBadge({ status }: { status: ExtractionJob["status"] | string }) {
  const failed = status === "failed";
  const busy = isExtractionBusy(status);
  return (
    <Badge
      variant="outline"
      className={cn(
        "border-transparent",
        failed && "bg-red-50 text-red-700 ring-1 ring-red-200",
        busy && "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
        !failed && !busy && "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
      )}
    >
      {extractionStatusLabel(status)}
    </Badge>
  );
}

export function SourceBadge({ sourceType, sourceId }: { sourceType: string; sourceId?: number | null }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
      {sourceLabel(sourceType)}
      {sourceId ? <span className="text-slate-400">#{sourceId}</span> : null}
    </span>
  );
}
