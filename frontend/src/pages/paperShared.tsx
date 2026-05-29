import { Badge } from "@/components/ui/badge";
import { DocumentStatus, ExtractionJob, PaperDetail, PaperListItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export const DEFAULT_EXTRACTION_QUERY = "提取研究目的、材料与方法、实验分组、关键性能指标（含具体数值）、图表数据、主要结论";

export const EXTRACTION_PRESETS: Array<{ label: string; query: string }> = [
  { label: "综合提取", query: "提取研究目的、材料与方法、实验分组、关键性能指标（含具体数值）、图表数据、主要结论" },
  { label: "材料科学", query: "提取材料组成配方、制备工艺参数（温度、时间、浓度）、表征结果（XRD/SEM/力学性能数值）、对比实验分组、图表中的定量数据" },
  { label: "生物医学", query: "提取实验菌株/细胞系、培养条件、药物浓度梯度、统计学指标（IC50/MIC/存活率）、图表中的柱状图和折线图数值" },
  { label: "机器学习", query: "提取模型架构、数据集规模与划分、超参数设置、评估指标（Accuracy/F1/AUC及具体数值）、与baseline的对比结果、消融实验数据" },
  { label: "仅图表数据", query: "只提取论文中所有图片和表格的定量数据，包括坐标轴数值、柱状图高度、折线图趋势、表格中的实验结果数值" },
];

export const FIELD_LABELS: Record<string, string> = {
  materials: "材料组成",
  experiment_groups: "实验分组",
  key_metrics: "关键指标",
  conclusion: "主要结论",
  research_purpose: "研究目的",
  methods: "材料与方法",
  figure_data: "图表数据",
  parameters: "工艺参数",
  model_architecture: "模型架构",
  dataset: "数据集",
  hyperparameters: "超参数",
  evaluation_metrics: "评估指标",
  ablation: "消融实验",
  characterization: "表征结果",
  statistical_results: "统计结果",
};

export const METRIC_ORDER = ["research_purpose", "materials", "methods", "experiment_groups", "parameters", "key_metrics", "figure_data", "conclusion"];

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

export function canExtractPaperListItem(paper?: PaperListItem | null) {
  if (!paper) return false;
  if (paper.status === "done" || paper.status === "parsed" || paper.status === "completed") return true;
  const counts = paper.asset_counts ?? {};
  return Boolean((counts.table ?? 0) || (counts.figure ?? 0) || (counts.page_snapshot ?? 0));
}

export function shouldPollPaper(paper?: PaperDetail | null) {
  return isPaperBusy(paper?.status) || isExtractionBusy(paper?.latest_extraction_job?.status);
}

export function fieldLabel(fieldName: string) {
  return FIELD_LABELS[fieldName] ?? fieldName;
}

export function confidencePercent(confidence?: number | null) {
  if (confidence === null || confidence === undefined) return null;
  return Math.round(confidence * 100);
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
