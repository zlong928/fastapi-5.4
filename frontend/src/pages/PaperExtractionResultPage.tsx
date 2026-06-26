import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, AlertTriangle, ArrowLeft, Braces, Check, CheckCircle2, Download, FileText, Image, Loader2, MapPin, MousePointer2, Play, RefreshCw, RotateCw, Table2, X, XCircle } from "lucide-react";
import { useEffect, useState, type MouseEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { API_BASE_URL, getPaper, getPaperAssetBlob, getStructuredExtraction, getToken, retryExtraction, runPaperAssetCoordinatePreview } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { CoordinatePreview, PaperFigureAssetItem, StructuredExtractionResponse, StructuredFigureResult, StructuredTableResult, StructuredTextResult } from "@/lib/types";
import { ExtractionStatusBadge, fieldLabel, isExtractionBusy, shouldPollPaper } from "@/pages/paperShared";
import { cn } from "@/lib/utils";

/* ─── Data Point type (local, no ECharts dependency) ─── */
type DataPoint = {
  x_value: number;
  y_value: number;
  series_name?: string;
  error_bar?: string;
};

/* ─── Helpers ─── */

function confidenceColor(c?: string | null) {
  if (c === "high") return "text-emerald-700 bg-emerald-50 ring-emerald-200";
  if (c === "medium") return "text-amber-700 bg-amber-50 ring-amber-200";
  if (c === "low") return "text-red-600 bg-red-50 ring-red-200";
  return "text-slate-500 bg-slate-50 ring-slate-200";
}

function ConfidenceBadge({ confidence }: { confidence?: string | null }) {
  if (!confidence) return null;
  const labels: Record<string, string> = { high: "高置信", medium: "中置信", low: "低置信" };
  return <Badge variant="outline" className={`border-transparent ring-1 text-[10px] ${confidenceColor(confidence)}`}>{labels[confidence] ?? confidence}</Badge>;
}

function evidenceTypeLabel(type?: string | null) {
  const labels: Record<string, string> = {
    text: "正文",
    table: "表格",
    figure: "图片",
    chart: "图表",
    equation: "公式",
    page_region: "页面区域",
    unknown: "未知",
  };
  return labels[type || ""] ?? type;
}

function sourceLabel(source?: string | null) {
  if (!source || source === "page_visual_snapshot" || source === "fallback_snapshot" || source === "page_snapshot") return null;
  const labels: Record<string, string> = {
    extracted_image: "嵌入图片",
    rendered_figure_region: "图注裁剪",
    mineru_chart: "MinerU 图表",
    mineru_image: "MinerU 图片",
    mineru_markdown: "MinerU 图片",
    table: "表格资产",
    figure: "图片资产",
  };
  return labels[source] ?? source;
}

function EvidenceMeta({ page, evidenceType, source, identifier }: { page?: number | null; evidenceType?: string | null; source?: string | null; identifier?: string | null }) {
  const items = [
    page ? `p.${page}` : null,
    evidenceTypeLabel(evidenceType),
    sourceLabel(source),
    identifier,
  ].filter(Boolean);
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
      <MapPin className="h-3.5 w-3.5 text-slate-400" />
      {items.map((item, index) => (
        <Badge key={`${item}-${index}`} variant="outline" className="border-slate-200 bg-white px-1.5 py-0 text-[10px] font-normal text-slate-500">
          {item}
        </Badge>
      ))}
    </div>
  );
}

function coordinatePreviewStatusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    accepted: "已标定",
    review_required: "需复核",
    skipped: "已跳过",
    failed: "失败",
  };
  return labels[status || ""] ?? status ?? "";
}

function coordinatePreviewTone(status?: string | null) {
  if (status === "accepted") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "review_required") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function downloadCoordinatePreview(preview: CoordinatePreview, figureLabel: string) {
  if (!preview.csv_url) {
    alert("暂无 CSV，请先生成数据提取");
    return;
  }
  const token = getToken();
  fetch(`${API_BASE_URL}${preview.csv_url}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
    .then((response) => {
      if (!response.ok) throw new Error("CSV 下载失败");
      return response.blob();
    })
    .then((blob) => {
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      const safeLabel = figureLabel.replace(/[^\w.-]+/g, "_") || "figure";
      link.href = url;
      link.download = `${safeLabel}_coordinate_preview.csv`;
      document.body.appendChild(link);
      link.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(link);
    })
    .catch((error) => {
      alert(error.message || "CSV 下载失败");
    });
}

/* ─── Image Preview ─── */

function FigureImage({ imageUrl }: { imageUrl?: string | null }) {
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSrc(""); setFailed(false);
    if (!imageUrl) return () => {};
    getPaperAssetBlob(imageUrl).then((blob) => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setSrc(objectUrl);
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [imageUrl]);

  if (!imageUrl || failed) return <div className="flex aspect-[4/3] items-center justify-center rounded-lg bg-slate-100 text-xs text-slate-400"><Image className="mr-1 h-4 w-4" />无法预览</div>;
  if (!src) return <div className="flex aspect-[4/3] items-center justify-center rounded-lg bg-slate-100 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /></div>;
  return <img src={src} alt="" className="aspect-[4/3] w-full rounded-lg bg-slate-100 object-contain" />;
}

/* ─── Summary Cards ─── */

function SummaryBar({ data }: { data: StructuredExtractionResponse }) {
  const s = data.summary;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      <SummaryCard icon={Image} label="图片分析" value={s.figures_analyzed} color="text-blue-600" />
      <SummaryCard icon={Table2} label="表格分析" value={s.tables_analyzed} color="text-emerald-600" />
      <SummaryCard icon={FileText} label="正文提取" value={s.text_items_extracted} color="text-slate-600" />
      <SummaryCard icon={CheckCircle2} label="总结果" value={s.total_results} color="text-slate-900" />
      <SummaryCard icon={XCircle} label="未找到" value={s.failed_items} color="text-red-500" />
    </div>
  );
}

function SummaryCard({ icon: Icon, label, value, color }: { icon: typeof FileText; label: string; value: number; color: string }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-3 shadow-sm">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500"><Icon className={`h-3.5 w-3.5 ${color}`} />{label}</div>
      <p className="mt-1.5 text-xl font-bold text-slate-900">{value}</p>
    </div>
  );
}

/* ─── Table Result Card ─── */

function TableResultCard({ item, index, selected, onToggle, selectionMode }: { item: StructuredTableResult; index: number; selected: boolean; onToggle: () => void; selectionMode: boolean }) {
  const hasStructured = Boolean(item.structured_data);
  let rows: string[][] = [];
  if (hasStructured) {
    try { const p = JSON.parse(item.structured_data!); if (Array.isArray(p) && p.length >= 2) rows = p; } catch {}
  }
  return (
    <article className={cn("rounded-xl border bg-white p-4 shadow-sm space-y-2.5 transition", selected ? "border-emerald-500 ring-2 ring-emerald-500" : "border-slate-200")}>
      {selectionMode && (
        <div className="flex items-center gap-2 pb-2 border-b border-slate-100">
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              "flex h-5 w-5 shrink-0 items-center justify-center rounded border transition",
              selected ? "border-emerald-600 bg-emerald-600 text-white" : "border-slate-300 bg-white hover:border-slate-400"
            )}
          >
            {selected ? <Check className="h-3.5 w-3.5" /> : null}
          </button>
          <span className="text-xs text-slate-500">表格 #{index + 1}</span>
        </div>
      )}
      <div className="flex items-start justify-between gap-2">
        <div>
          {item.table_id ? <p className="text-[11px] font-medium text-emerald-600">{item.table_id}</p> : null}
          <h3 className="text-sm font-semibold text-slate-900">{fieldLabel(item.metric)}</h3>
        </div>
        <div className="flex gap-1">
          {item.parse_status === "success" ? <Badge variant="outline" className="border-transparent bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 text-[10px]">结构化</Badge> : null}
          {item.parse_status === "partial" ? <Badge variant="outline" className="border-transparent bg-amber-50 text-amber-700 ring-1 ring-amber-200 text-[10px]">部分解析</Badge> : null}
          {item.parse_status === "failed" ? <Badge variant="outline" className="border-transparent bg-red-50 text-red-600 ring-1 ring-red-200 text-[10px]">解析失败</Badge> : null}
        </div>
      </div>
      <EvidenceMeta page={item.page} evidenceType={item.evidence_type} source={item.source} identifier={item.table_id} />
      {rows.length >= 2 ? (
        <div className="overflow-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-50"><tr>{rows[0].map((h, i) => <th key={i} className="px-2.5 py-1.5 text-left font-medium text-slate-600">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">{rows.slice(1, 8).map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci} className="px-2.5 py-1.5 text-slate-700">{cell}</td>)}</tr>)}</tbody>
          </table>
          {rows.length > 8 ? <p className="px-2.5 py-1 text-[10px] text-slate-400">共 {rows.length - 1} 行</p> : null}
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{item.value}</p>
      )}
      {item.evidence ? (
        <div className="rounded-lg bg-slate-50 p-2.5">
          <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">证据来源</p>
          <p className="line-clamp-3 text-xs leading-5 text-slate-600">{item.evidence}</p>
        </div>
      ) : null}
      {item.notes ? <p className="text-xs italic text-slate-500">{item.notes}</p> : null}
    </article>
  );
}

/* ─── Text Result Card ─── */

function TextResultCard({ item, index, selected, onToggle, selectionMode }: { item: StructuredTextResult; index: number; selected: boolean; onToggle: () => void; selectionMode: boolean }) {
  return (
    <article className={cn("rounded-xl border bg-white p-4 shadow-sm space-y-2 transition", selected ? "border-slate-500 ring-2 ring-slate-500" : "border-slate-200")}>
      {selectionMode && (
        <div className="flex items-center gap-2 pb-2 border-b border-slate-100">
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              "flex h-5 w-5 shrink-0 items-center justify-center rounded border transition",
              selected ? "border-slate-600 bg-slate-600 text-white" : "border-slate-300 bg-white hover:border-slate-400"
            )}
          >
            {selected ? <Check className="h-3.5 w-3.5" /> : null}
          </button>
          <span className="text-xs text-slate-500">文本 #{index + 1}</span>
        </div>
      )}
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{fieldLabel(item.metric)}</h3>
        <ConfidenceBadge confidence={item.confidence} />
      </div>
      <EvidenceMeta page={item.page} evidenceType={item.evidence_type} source={item.source} />
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{item.value}</p>
      {item.evidence ? (
        <div className="rounded-lg bg-slate-50 p-2.5">
          <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">原文证据</p>
          <p className="line-clamp-4 text-xs leading-5 text-slate-600">{item.evidence}</p>
        </div>
      ) : null}
    </article>
  );
}

/* ─── Chart Data Helpers ─── */

const CSV_META_COLUMNS = new Set([
  "indicator", "series_name", "x_unit", "y_unit",
  "x_scale", "y_scale", "confidence", "quality_tags",
  "panel_id", "curve_role",
]);

function csvToDataPoints(columns: string[], rows: Record<string, string>[]): DataPoint[] {
  const dataCols = columns.filter((c) => !CSV_META_COLUMNS.has(c));
  const xCol = dataCols[0] || columns[0];
  const yCol = dataCols[1] || (columns.length >= 2 ? columns[1] : columns[0]);
  const pts: DataPoint[] = [];
  for (const row of rows) {
    const x = Number(row[xCol]);
    const y = Number(row[yCol]);
    if (Number.isNaN(x) || Number.isNaN(y)) continue;
    const pt: DataPoint = { x_value: x, y_value: y };
    if (row.series_name) pt.series_name = row.series_name;
    if (row.error_bar) pt.error_bar = row.error_bar;
    pts.push(pt);
  }
  return pts;
}

/* ─── Result Body ─── */

const EXTRACTION_TARGETS = [
  { id: "rheology_strain_sweep", label: "应变扫描", targets: ["G'", "G''", "strain", "modulus"] },
  { id: "rheology_flow_curve", label: "流动曲线", targets: ["viscosity", "shear rate"] },
  { id: "rheology_step_time_sweep", label: "时间扫描", targets: ["time", "viscosity", "shear rate"] },
  { id: "line_plot", label: "折线/时序", targets: ["x", "y", "series"] },
  { id: "bar_chart", label: "柱状图", targets: ["category", "value"] },
  { id: "scatter_plot", label: "散点/拟合", targets: ["x", "y", "fit"] },
];

function parseCsvLine(line: string) {
  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"' && line[index + 1] === '"') {
      current += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === "," && !quoted) {
      cells.push(current);
      current = "";
    } else {
      current += character;
    }
  }
  cells.push(current);
  return cells;
}

function useCoordinateCsv(preview?: CoordinatePreview | null) {
  const [dataPoints, setDataPoints] = useState<DataPoint[]>([]);
  const [xLabel, setXLabel] = useState("");
  const [yLabel, setYLabel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setDataPoints([]);
    setXLabel("");
    setYLabel("");
    setError("");
    if (!preview?.csv_url) return () => {};
    setLoading(true);
    const token = getToken();
    fetch(`${API_BASE_URL}${preview.csv_url}`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
      .then((response) => {
        if (!response.ok) throw new Error("CSV 读取失败");
        return response.text();
      })
      .then((text) => {
        if (cancelled) return;
        const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
        if (!lines.length) return;
        const columns = parseCsvLine(lines[0]);
        const rows = lines.slice(1).map((line) => {
          const cells = parseCsvLine(line);
          return Object.fromEntries(columns.map((column, idx) => [column, cells[idx] ?? ""]));
        });
        // Detect data column labels for ChartDataViewer
        const dataCols = columns.filter((c) => !CSV_META_COLUMNS.has(c));
        if (dataCols.length >= 1) setXLabel(dataCols[0]);
        if (dataCols.length >= 2) setYLabel(dataCols[1]);
        setDataPoints(csvToDataPoints(columns, rows));
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "CSV 读取失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [preview?.csv_url]);

  return { dataPoints, xLabel, yLabel, loading, error };
}

function DataTable({ dataPoints, xLabel, yLabel }: { dataPoints: DataPoint[]; xLabel?: string; yLabel?: string }) {
  const hasSeries = dataPoints.some((p) => p.series_name);
  const hasError = dataPoints.some((p) => p.error_bar);
  const xh = xLabel || "x";
  const yh = yLabel || "y";
  return (
    <div className="max-h-72 overflow-auto rounded-md border border-slate-200">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-50 text-left text-[11px] text-slate-500">
          <tr>
            {hasSeries ? <th className="border-b border-slate-100 px-3 py-2 font-medium">series</th> : null}
            <th className="border-b border-slate-100 px-3 py-2 font-medium">{xh}</th>
            <th className="border-b border-slate-100 px-3 py-2 font-medium">{yh}</th>
            {hasError ? <th className="border-b border-slate-100 px-3 py-2 font-medium">error</th> : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {dataPoints.slice(0, 200).map((pt, i) => (
            <tr key={i}>
              {hasSeries ? <td className="max-w-[120px] truncate px-3 py-2 text-slate-600">{pt.series_name || "—"}</td> : null}
              <td className="max-w-[180px] truncate px-3 py-2 font-mono text-slate-700">{pt.x_value}</td>
              <td className="max-w-[180px] truncate px-3 py-2 font-mono text-slate-700">{pt.y_value}</td>
              {hasError ? <td className="max-w-[120px] truncate px-3 py-2 text-slate-500">{pt.error_bar || ""}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
      {dataPoints.length > 200 ? <p className="px-3 py-1 text-[10px] text-slate-400">共 {dataPoints.length} 行，仅显示前 200 行</p> : null}
    </div>
  );
}

function CoordinateCsvPreview({ preview }: { preview?: CoordinatePreview | null }) {
  const { dataPoints, xLabel: csvXLabel, yLabel: csvYLabel, loading, error } = useCoordinateCsv(preview);
  if (!preview?.csv_url) {
    return (
      <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-slate-200 text-sm text-slate-500">
        暂无 CSV，点击生成后会在这里显示
      </div>
    );
  }
  if (loading) {
    return <div className="flex h-40 items-center justify-center text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /></div>;
  }
  if (error) {
    return <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>;
  }
  if (!dataPoints.length) {
    return <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-slate-200 text-sm text-slate-500">CSV 为空</div>;
  }
  return (
    <DataTable
      dataPoints={dataPoints}
      xLabel={csvXLabel || preview.semantic_columns?.[0]}
      yLabel={csvYLabel || preview.semantic_columns?.[1]}
    />
  );
}

function FigureExtractionDialog({
  figure,
  onClose,
  onGenerated,
}: {
  figure: PaperFigureAssetItem;
  onClose: () => void;
  onGenerated: () => void;
}) {
  const [chartType, setChartType] = useState(figure.coordinate_preview?.image_type || "auto");
  const [targets, setTargets] = useState<string[]>(figure.coordinate_preview?.targets?.length ? figure.coordinate_preview.targets : []);
  const [preview, setPreview] = useState<CoordinatePreview | null | undefined>(figure.coordinate_preview);
  const runMutation = useMutation({
    mutationFn: () => runPaperAssetCoordinatePreview(figure.id, {
      chart_type: chartType || "auto",
      targets,
      sample_limit: 120,
      force_regenerate: Boolean(preview?.csv_url),
    }),
    onSuccess: (nextPreview) => {
      setPreview(nextPreview);
      onGenerated();
    },
  });

  function toggleTarget(target: string) {
    setTargets((current) => current.includes(target) ? current.filter((item) => item !== target) : [...current, target]);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="grid max-h-[92vh] w-full max-w-6xl overflow-hidden rounded-lg bg-white shadow-2xl lg:grid-cols-[420px_minmax(0,1fr)]">
        <div className="min-h-0 overflow-auto border-r border-slate-200 bg-slate-50 p-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-slate-500">图片资产 #{figure.id}</p>
              <h2 className="truncate text-base font-semibold text-slate-950">{figure.figure_label}</h2>
            </div>
            <Button type="button" variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          <FigureImage imageUrl={figure.image_url} />
          <div className="mt-3 space-y-2">
            <EvidenceMeta page={figure.page} evidenceType="figure" source={figure.source} identifier={figure.asset_type} />
            {figure.caption ? <p className="text-xs leading-5 text-slate-600">{figure.caption}</p> : null}
          </div>
        </div>

        <div className="min-h-0 overflow-auto p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-950">单图数据提取</h3>
              <p className="mt-1 text-xs text-slate-500">选择图类型或字段后运行，只处理当前这张解析图片资产。</p>
            </div>
            {preview ? (
              <Badge variant="outline" className={cn("border text-[10px]", coordinatePreviewTone(preview.status))}>
                {coordinatePreviewStatusLabel(preview.status)}
              </Badge>
            ) : null}
          </div>

          <div className="mt-4 space-y-4">
            <div>
              <p className="mb-2 text-xs font-medium text-slate-600">可交互字段</p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setChartType("auto")}
                  className={cn("rounded-md border px-2.5 py-1.5 text-xs transition", chartType === "auto" ? "border-slate-900 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")}
                >
                  自动识别
                </button>
                {EXTRACTION_TARGETS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      setChartType(item.id);
                      setTargets((current) => Array.from(new Set([...current, ...item.targets])));
                    }}
                    className={cn("rounded-md border px-2.5 py-1.5 text-xs transition", chartType === item.id ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-xs font-medium text-slate-600">提取目标</p>
              <div className="flex flex-wrap gap-2">
                {["x", "y", "series", "panel", "G'", "G''", "strain", "viscosity", "shear rate", "time", "category", "value"].map((target) => (
                  <button
                    key={target}
                    type="button"
                    onClick={() => toggleTarget(target)}
                    className={cn("rounded-md border px-2.5 py-1.5 text-xs transition", targets.includes(target) ? "border-emerald-500 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")}
                  >
                    {target}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
                {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {preview?.csv_url ? "刷新数据提取" : "生成数据提取"}
              </Button>
              {preview?.csv_url ? (
                <Button type="button" variant="outline" onClick={() => downloadCoordinatePreview(preview, figure.figure_label)}>
                  <Download className="h-4 w-4" />
                  下载 CSV
                </Button>
              ) : null}
              {preview ? <span className="text-xs text-slate-500">{preview.row_count} 行 · {preview.image_type || "未分类"}</span> : null}
            </div>

            {runMutation.isPending ? (
              <Alert>
                <Loader2 className="h-4 w-4 animate-spin" />
                <AlertDescription>正在处理图表数据提取，这可能需要 10-30 秒...</AlertDescription>
              </Alert>
            ) : null}

            {runMutation.error ? (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{runMutation.error instanceof Error ? runMutation.error.message : "图片提取失败"}</AlertDescription>
              </Alert>
            ) : null}

            {preview ? (
              <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-3">
                <div><span className="text-slate-400">类型</span><br />{preview.image_type || "-"}</div>
                <div><span className="text-slate-400">处理器</span><br />{preview.selected_extractor || "-"}</div>
                <div><span className="text-slate-400">质量</span><br />{preview.data_quality || "-"}</div>
              </div>
            ) : null}

            <CoordinateCsvPreview preview={preview} />
          </div>
        </div>
      </div>
    </div>
  );
}

function PaperFigureCoordinateCard({ figure, onOpen, onGenerated }: { figure: PaperFigureAssetItem; onOpen: () => void; onGenerated: () => void }) {
  const [localPreview, setLocalPreview] = useState<CoordinatePreview | null | undefined>(figure.coordinate_preview);
  const runMutation = useMutation({
    mutationFn: () => runPaperAssetCoordinatePreview(figure.id, {
      chart_type: localPreview?.chart_type_hint || localPreview?.image_type || "auto",
      targets: localPreview?.targets ?? [],
      sample_limit: 120,
      force_regenerate: Boolean(localPreview?.csv_url),
    }),
    onSuccess: (nextPreview) => {
      setLocalPreview(nextPreview);
      onGenerated();
    },
  });

  useEffect(() => {
    setLocalPreview(figure.coordinate_preview);
  }, [figure.coordinate_preview, figure.id]);

  function runPreview(event: MouseEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!runMutation.isPending) runMutation.mutate();
  }

  const preview = localPreview;
  const canDownload = Boolean(preview?.csv_url);

  return (
    <article className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition hover:border-blue-300 hover:ring-2 hover:ring-blue-100">
      <button type="button" onClick={onOpen} className="block w-full text-left">
        <FigureImage imageUrl={figure.image_url} />
      </button>
      <div className="p-2.5">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-xs font-medium text-slate-900">{figure.figure_label}</p>
          <button
            type="button"
            onClick={onOpen}
            className="rounded p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            aria-label={`查看 ${figure.figure_label}`}
          >
            <MousePointer2 className="h-3.5 w-3.5" />
          </button>
        </div>
        <p className="mt-0.5 text-[10px] text-slate-400">page {figure.page ?? "-"} · {figure.source || figure.asset_type}</p>
        {figure.caption ? <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{figure.caption}</p> : null}
        {preview ? (
          <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-2">
            <div className="flex items-center justify-between gap-2">
              <Badge variant="outline" className={cn("border text-[10px]", coordinatePreviewTone(preview.status))}>
                {coordinatePreviewStatusLabel(preview.status)}
              </Badge>
              <span className="text-[10px] text-slate-400">CSV</span>
            </div>
            <p className="mt-1 text-[10px] leading-4 text-slate-500">
              {preview.row_count} 行 · {preview.image_type || preview.data_quality || "未标注类型"}
            </p>
          </div>
        ) : (
          <button
            type="button"
            className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-blue-200 bg-blue-50 px-2 py-2 text-[11px] font-medium text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 disabled:cursor-wait disabled:opacity-70"
            onClick={runPreview}
            disabled={runMutation.isPending}
          >
            {runMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {runMutation.isPending ? "正在生成数据提取" : "点击生成数据提取"}
          </button>
        )}
      </div>
      {preview?.csv_url ? (
        <div className="grid grid-cols-2 gap-2 border-t border-slate-100 p-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={runPreview}
            disabled={runMutation.isPending}
          >
            {runMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            刷新数据提取
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={(event) => {
              event.stopPropagation();
              downloadCoordinatePreview(preview, figure.figure_label);
            }}
            disabled={!canDownload || runMutation.isPending}
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </Button>
        </div>
      ) : null}
      {runMutation.error ? (
        <p className="border-t border-red-100 bg-red-50 px-2 py-1.5 text-[10px] leading-4 text-red-700">
          {runMutation.error instanceof Error ? runMutation.error.message : "图片提取失败"}
        </p>
      ) : null}
    </article>
  );
}

function PaperFiguresGallery({ figures, onGenerated }: { figures: PaperFigureAssetItem[]; onGenerated: () => void }) {
  const [activeFigure, setActiveFigure] = useState<PaperFigureAssetItem | null>(null);
  const coordinateFigures = figures.filter((figure) => figure.coordinate_capable);
  if (!coordinateFigures.length) return null;
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Image className="h-4 w-4 text-indigo-500" />
        <h2 className="text-sm font-semibold text-slate-900">可提取坐标的图表</h2>
        <Badge variant="outline" className="text-[10px]">{coordinateFigures.length}</Badge>
        <span className="text-xs text-slate-500">点击单张图生成或查看 CSV</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {coordinateFigures.map((fig) => (
          <PaperFigureCoordinateCard
            key={fig.id}
            figure={fig}
            onOpen={() => setActiveFigure(fig)}
            onGenerated={onGenerated}
          />
        ))}
      </div>
      {activeFigure ? (
        <FigureExtractionDialog
          figure={activeFigure}
          onClose={() => setActiveFigure(null)}
          onGenerated={onGenerated}
        />
      ) : null}
    </section>
  );
}

/* ─── Figure Result Card ─── */

function FigureResultCard({ figure }: { figure: StructuredFigureResult }) {
  // Try CSV fetch first (semantic headers from write_coordinate_csv format)
  const [csvDataPoints, setCsvDataPoints] = useState<DataPoint[]>([]);
  const [csvCols, setCsvCols] = useState<{ x: string; y: string }>({ x: "x", y: "y" });
  const [csvLoading, setCsvLoading] = useState(false);

  useEffect(() => {
    if (!figure.csv_url) return;
    let cancelled = false;
    setCsvLoading(true);
    const token = getToken();
    fetch(`${API_BASE_URL}${figure.csv_url}`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
      .then((r) => { if (!r.ok) throw new Error("CSV fetch failed"); return r.text(); })
      .then((text) => {
        if (cancelled) return;
        const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
        if (!lines.length) return;
        const cols = parseCsvLine(lines[0]);
        const dataCols = cols.filter((c) => !CSV_META_COLUMNS.has(c));
        const xc = dataCols[0] || cols[0];
        const yc = dataCols[1] || (cols.length >= 2 ? cols[1] : cols[0]);
        setCsvCols({ x: xc, y: yc });
        const rows = lines.slice(1).map((l) => {
          const cells = parseCsvLine(l);
          return Object.fromEntries(cols.map((col, i) => [col, cells[i] ?? ""]));
        });
        setCsvDataPoints(csvToDataPoints(cols, rows));
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setCsvLoading(false); });
    return () => { cancelled = true; };
  }, [figure.csv_url]);

  // Fallback: parse data_points from JSON API response
  const jsonDataPoints: DataPoint[] = (() => {
    const raw = figure.data_points;
    if (!Array.isArray(raw) || raw.length === 0) return [];
    const pts: DataPoint[] = [];
    for (const p of raw) {
      if (!p || typeof p !== "object") continue;
      const r = p as Record<string, string | number>;
      const x = typeof r.x_value === "number" ? r.x_value : Number(r.x_value);
      const y = typeof r.y_value === "number" ? r.y_value : Number(r.y_value);
      if (!Number.isNaN(x) && !Number.isNaN(y)) {
        pts.push({
          x_value: x,
          y_value: y,
          series_name: String(r.series_name ?? r.series ?? ""),
          error_bar: String(r.error_bar ?? ""),
        });
      }
    }
    return pts;
  })();

  // Use CSV data when available, fall back to JSON
  const dataPoints = csvDataPoints.length > 0 ? csvDataPoints : jsonDataPoints;
  const xLabel = csvCols.x || figure.x_axis_label || figure.image_type || "x";
  const yLabel = csvCols.y || figure.y_axis_label || figure.metric || "y";

  return (
    <article className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-3 p-4 sm:flex-row">
        {figure.image_url ? (
          <div className="w-full shrink-0 sm:w-48">
            <FigureImage imageUrl={figure.image_url} />
          </div>
        ) : null}
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              {figure.figure_id ? <p className="text-[11px] font-medium text-indigo-600">{figure.figure_id}</p> : null}
              <h3 className="text-sm font-semibold text-slate-900">{fieldLabel(figure.metric)}</h3>
              <p className="mt-0.5 text-xs text-slate-500">{figure.value}</p>
            </div>
            <ConfidenceBadge confidence={figure.confidence} />
          </div>
          <EvidenceMeta page={figure.page} evidenceType={figure.evidence_type} source={figure.source} identifier={figure.figure_id} />
          {figure.caption ? <p className="line-clamp-2 text-xs leading-5 text-slate-500">{figure.caption}</p> : null}

          {csvLoading ? (
            <div className="flex h-24 items-center justify-center text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /></div>
          ) : dataPoints.length > 0 ? (
            <DataTable dataPoints={dataPoints} xLabel={xLabel} yLabel={yLabel} />
          ) : figure.evidence ? (
            <div className="rounded-lg bg-slate-50 p-2.5">
              <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">来源</p>
              <p className="text-xs leading-5 text-slate-600">{figure.evidence}</p>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function ResultBody({ data, jobId }: { data: StructuredExtractionResponse; jobId: number }) {
  const [showRaw, setShowRaw] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedResultIds, setSelectedResultIds] = useState<number[]>([]);
  const queryClient = useQueryClient();

  const hasFigures = data.figure_results.length > 0;
  const hasTables = data.table_results.length > 0;
  const hasText = data.text_results.length > 0;
  const hasPaperFigures = (data.paper_figures ?? []).some((figure) => figure.coordinate_capable);

  const totalSelected = selectedResultIds.length;
  const totalItems = data.table_results.length + data.text_results.length;

  function toggleResult(resultId: number) {
    setSelectedResultIds(prev => prev.includes(resultId) ? prev.filter(id => id !== resultId) : [...prev, resultId]);
  }

  function selectAll() {
    const allIds = [
      ...data.table_results.map(r => r.id),
      ...data.text_results.map(r => r.id)
    ];
    setSelectedResultIds(allIds);
  }

  function clearSelection() {
    setSelectedResultIds([]);
  }

  function exportResults(format: "csv" | "json" | "markdown" | "xlsx") {
    const token = getToken();

    // Build URL with result_ids if in selection mode and items are selected
    let url = `${API_BASE_URL}/extractions/${jobId}/export?format=${format}`;
    if (selectionMode && selectedResultIds.length > 0) {
      selectedResultIds.forEach(id => {
        url += `&result_ids=${id}`;
      });
    }

    fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(response => {
        if (!response.ok) throw new Error("导出失败");
        return response.blob();
      })
      .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const suffix = selectionMode && selectedResultIds.length > 0 ? `_selected_${selectedResultIds.length}` : '';
        a.download = `extraction_${jobId}${suffix}.${format}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      })
      .catch(error => {
        alert(error.message || "导出失败");
      });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant={selectionMode ? "default" : "outline"}
            size="sm"
            onClick={() => {
              setSelectionMode(!selectionMode);
              if (selectionMode) clearSelection();
            }}
          >
            <Check className="h-4 w-4" />
            {selectionMode ? "退出选择" : "批量选择"}
          </Button>
          {selectionMode && (
            <>
              <span className="text-sm text-slate-500">已选 {totalSelected} / {totalItems}</span>
              {totalSelected < totalItems ? (
                <Button type="button" variant="ghost" size="sm" onClick={selectAll}>全选</Button>
              ) : (
                <Button type="button" variant="ghost" size="sm" onClick={clearSelection}>清空</Button>
              )}
            </>
          )}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger>
            <Button type="button" size="sm">
              <Download className="h-4 w-4" />
              导出结果
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => exportResults("csv")}>导出为 CSV</DropdownMenuItem>
            <DropdownMenuItem onClick={() => exportResults("json")}>导出为 JSON</DropdownMenuItem>
            <DropdownMenuItem onClick={() => exportResults("xlsx")}>导出为 Excel (图表数据)</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => exportResults("markdown")}>导出为 Markdown</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <SummaryBar data={data} />

      {hasPaperFigures ? (
        <PaperFiguresGallery
          figures={data.paper_figures}
          onGenerated={() => queryClient.invalidateQueries({ queryKey: ["extraction-structured", jobId] })}
        />
      ) : null}

      {hasFigures ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Image className="h-4 w-4 text-indigo-500" />
            <h2 className="text-sm font-semibold text-slate-900">图表提取</h2>
            <Badge variant="outline" className="text-[10px]">{data.figure_results.length}</Badge>
            {selectionMode && selectedResultIds.filter(id => data.figure_results.some(f => f.id === id)).length > 0 && (
              <Badge variant="outline" className="bg-indigo-50 text-indigo-600 text-[10px]">已选 {selectedResultIds.filter(id => data.figure_results.some(f => f.id === id)).length}</Badge>
            )}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.figure_results.map((fig) => (
              <FigureResultCard key={fig.id} figure={fig} />
            ))}
          </div>
        </section>
      ) : null}

      {hasTables ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Table2 className="h-4 w-4 text-emerald-500" />
            <h2 className="text-sm font-semibold text-slate-900">表格数据</h2>
            <Badge variant="outline" className="text-[10px]">{data.table_results.length}</Badge>
            {selectionMode && selectedResultIds.filter(id => data.table_results.some(r => r.id === id)).length > 0 && (
              <Badge variant="outline" className="bg-emerald-50 text-emerald-600 text-[10px]">已选 {selectedResultIds.filter(id => data.table_results.some(r => r.id === id)).length}</Badge>
            )}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.table_results.map((item, i) => (
              <TableResultCard
                key={item.id}
                item={item}
                index={i}
                selected={selectedResultIds.includes(item.id)}
                onToggle={() => toggleResult(item.id)}
                selectionMode={selectionMode}
              />
            ))}
          </div>
        </section>
      ) : null}

      {hasText ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <FileText className="h-4 w-4 text-slate-500" />
            <h2 className="text-sm font-semibold text-slate-900">正文提取</h2>
            <Badge variant="outline" className="text-[10px]">{data.text_results.length}</Badge>
            {selectionMode && selectedResultIds.filter(id => data.text_results.some(r => r.id === id)).length > 0 && (
              <Badge variant="outline" className="bg-slate-50 text-slate-600 text-[10px]">已选 {selectedResultIds.filter(id => data.text_results.some(r => r.id === id)).length}</Badge>
            )}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.text_results.map((item, i) => (
              <TextResultCard
                key={item.id}
                item={item}
                index={i}
                selected={selectedResultIds.includes(item.id)}
                onToggle={() => toggleResult(item.id)}
                selectionMode={selectionMode}
              />
            ))}
          </div>
        </section>
      ) : null}

      {data.not_found.length > 0 ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h2 className="text-sm font-semibold text-slate-900">未找到的信息</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {data.not_found.map((item, i) => (
              <Badge key={i} variant="outline" className="border-amber-200 bg-amber-50 text-amber-700">{fieldLabel(item)}</Badge>
            ))}
          </div>
        </section>
      ) : null}

      <div className="pt-2">
        <Button variant="ghost" size="sm" className="text-xs text-slate-400" onClick={() => setShowRaw(!showRaw)}>
          <Braces className="mr-1 h-3.5 w-3.5" />{showRaw ? "收起" : "查看"} 原始 JSON
        </Button>
        {showRaw && <pre className="mt-2 max-h-96 overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(data, null, 2)}</pre>}
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

export function PaperExtractionResultPage() {
  const paperId = Number(useParams().id);
  const [searchParams] = useSearchParams();
  const selectedJobId = Number(searchParams.get("job"));
  const hasSelectedJob = Number.isFinite(selectedJobId) && selectedJobId > 0;
  const queryClient = useQueryClient();

  const paperQuery = useQuery({ queryKey: ["paper", paperId], queryFn: () => getPaper(paperId), enabled: Number.isFinite(paperId), refetchInterval: (q) => shouldPollPaper(q.state.data) ? 2000 : false });
  const structuredQuery = useQuery({
    queryKey: ["extraction-structured", selectedJobId],
    queryFn: () => getStructuredExtraction(selectedJobId),
    enabled: hasSelectedJob,
    refetchInterval: (q) => isExtractionBusy(q.state.data?.status) ? 2000 : false,
  });
  const retryMutation = useMutation({ mutationFn: (id: number) => retryExtraction(id), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["paper", paperId] }); queryClient.invalidateQueries({ queryKey: ["extraction-structured", selectedJobId] }); } });

  const paper = paperQuery.data;
  const data = structuredQuery.data;
  const loading = paperQuery.isLoading || (hasSelectedJob && structuredQuery.isLoading);

  if (loading) return <div className="flex min-h-[420px] items-center justify-center text-sm text-slate-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中</div>;
  if (!paper) return <Alert variant="destructive"><AlertDescription>论文不存在</AlertDescription></Alert>;

  return (
    <main className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 px-2 text-slate-500">
            <Link to={`/papers/${paperId}/extraction`}><ArrowLeft className="h-4 w-4" />提取任务</Link>
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            {data && <ExtractionStatusBadge status={data.status} />}
            {data && <span className="text-xs text-slate-400">#{selectedJobId} · {formatChinaDateTime(data.updated_at)}</span>}
          </div>
          <h1 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">{paper.title}</h1>
          {data && <p className="mt-1 max-w-2xl text-sm text-slate-500">{data.task}</p>}
        </div>
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm"><Link to={`/papers/${paper.id}`}><FileText className="h-4 w-4" />论文</Link></Button>
          <Button variant="outline" size="sm" onClick={() => { paperQuery.refetch(); structuredQuery.refetch(); }} disabled={structuredQuery.isFetching}>
            {structuredQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </Button>
        </div>
      </header>

      {!data && !hasSelectedJob && (
        <section className="rounded-xl border border-slate-200 bg-white p-10 text-center">
          <p className="text-sm text-slate-500">暂无提取结果</p>
          <Button asChild className="mt-4 rounded-xl"><Link to={`/papers/${paperId}/extraction`}>创建提取任务</Link></Button>
        </section>
      )}

      {data && isExtractionBusy(data.status) && (
        <section className="rounded-xl border border-slate-200 bg-white p-10 text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-slate-400" />
          <p className="mt-3 text-sm text-slate-600">提取任务执行中...</p>
        </section>
      )}

      {data?.status === "failed" && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>{data.error_message ?? "提取失败"}</span>
            <Button size="sm" variant="outline" className="border-red-200 text-red-700" onClick={() => retryMutation.mutate(selectedJobId)} disabled={retryMutation.isPending}>
              {retryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}重试
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {data?.status === "done" && <ResultBody data={data} jobId={selectedJobId} />}
    </main>
  );
}
