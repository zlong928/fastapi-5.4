import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Braces, Check, CheckCircle2, Download, FileText, Image, Loader2, MapPin, RefreshCw, RotateCw, Table2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { API_BASE_URL, getPaper, getPaperAssetBlob, getPaperChartTypes, getStructuredExtraction, getToken, retryExtraction } from "@/lib/api";
import { formatChinaDateTime } from "@/lib/time";
import { ChartTypeCatalogItem, ChartTypeRuntimeStats, CoordinatePreview, PaperFigureAssetItem, StructuredExtractionResponse, StructuredFigureResult, StructuredTableResult, StructuredTextResult } from "@/lib/types";
import { ExtractionStatusBadge, fieldLabel, isExtractionBusy, shouldPollPaper } from "@/pages/paperShared";
import { cn } from "@/lib/utils";

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
  const labels: Record<string, string> = {
    extracted_image: "嵌入图片",
    rendered_figure_region: "图注裁剪",
    page_visual_snapshot: "页面快照",
    fallback_snapshot: "兜底快照",
    table: "表格资产",
    figure: "图片资产",
    page_snapshot: "页面快照",
  };
  return source ? labels[source] ?? source : null;
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
  if (!preview.csv_url) return;
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

/* ─── Figure Result Card ─── */

function FigureResultCard({ item, index, selected, onToggle, selectionMode }: { item: StructuredFigureResult; index: number; selected: boolean; onToggle: () => void; selectionMode: boolean }) {
  return (
    <article className={cn("overflow-hidden rounded-xl border bg-white shadow-sm transition", selected ? "border-blue-500 ring-2 ring-blue-500" : "border-slate-200")}>
      {selectionMode && (
        <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2">
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              "flex h-5 w-5 shrink-0 items-center justify-center rounded border transition",
              selected ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white hover:border-slate-400"
            )}
          >
            {selected ? <Check className="h-3.5 w-3.5" /> : null}
          </button>
          <span className="text-xs text-slate-500">图片 #{index + 1}</span>
        </div>
      )}
      <FigureImage imageUrl={item.image_url} />
      <div className="space-y-2.5 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[11px] font-medium text-blue-600">{item.figure_id}</p>
            <h3 className="mt-0.5 text-sm font-semibold text-slate-900">{fieldLabel(item.metric)}</h3>
          </div>
          <ConfidenceBadge confidence={item.confidence} />
        </div>
        {item.caption ? <p className="text-xs leading-5 text-slate-500">{item.caption}</p> : null}
        <EvidenceMeta page={item.page} evidenceType={item.evidence_type} source={item.source} identifier={item.figure_id} />
        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{item.value}</p>
        {item.evidence ? (
          <div className="rounded-lg bg-slate-50 p-2.5">
            <p className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">证据来源</p>
            <p className="line-clamp-3 text-xs leading-5 text-slate-600">{item.evidence}</p>
          </div>
        ) : null}
        {item.notes ? <p className="text-xs italic text-slate-500">{item.notes}</p> : null}
      </div>
    </article>
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

/* ─── Result Body ─── */

function PaperFiguresGallery({ figures }: { figures: PaperFigureAssetItem[] }) {
  if (!figures.length) return null;
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Image className="h-4 w-4 text-indigo-500" />
        <h2 className="text-sm font-semibold text-slate-900">论文图片</h2>
        <Badge variant="outline" className="text-[10px]">{figures.length}</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {figures.map((fig) => (
          <article key={fig.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <FigureImage imageUrl={fig.image_url} />
            <div className="p-2.5">
              <p className="truncate text-xs font-medium text-slate-900">{fig.figure_label}</p>
              <p className="mt-0.5 text-[10px] text-slate-400">page {fig.page ?? "-"} · {fig.source || fig.asset_type}</p>
              {fig.caption ? <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{fig.caption}</p> : null}
              {fig.coordinate_preview ? (
                <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <Badge variant="outline" className={cn("border text-[10px]", coordinatePreviewTone(fig.coordinate_preview.status))}>
                      {coordinatePreviewStatusLabel(fig.coordinate_preview.status)}
                    </Badge>
                    {fig.coordinate_preview.csv_url ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 px-2 text-[11px]"
                        onClick={() => downloadCoordinatePreview(fig.coordinate_preview!, fig.figure_label)}
                      >
                        <Download className="h-3.5 w-3.5" />
                        CSV
                      </Button>
                    ) : null}
                  </div>
                  <p className="mt-1 text-[10px] leading-4 text-slate-500">
                    {fig.coordinate_preview.row_count} 点 · {fig.coordinate_preview.data_quality || "未标注质量"}
                  </p>
                </div>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ChartTypeMatrix({ items, stats }: { items: ChartTypeCatalogItem[]; stats: ChartTypeRuntimeStats[] }) {
  if (!items.length) return null;
  const statsByType = new Map(stats.map((item) => [item.image_type, item]));
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Braces className="h-4 w-4 text-slate-500" />
        <h2 className="text-sm font-semibold text-slate-900">图片处理矩阵</h2>
        <Badge variant="outline" className="text-[10px]">{items.length}</Badge>
      </div>
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-auto">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="bg-slate-50 text-left text-[11px] text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">类型</th>
                <th className="px-3 py-2 font-medium">处理链路</th>
                <th className="px-3 py-2 font-medium">CSV</th>
                <th className="px-3 py-2 font-medium">复核</th>
                <th className="px-3 py-2 font-medium">当前结果</th>
                <th className="px-3 py-2 font-medium">典型内容</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((item) => (
                <tr key={item.image_type}>
                  {(() => {
                    const stat = statsByType.get(item.image_type);
                    return (
                      <>
                  <td className="px-3 py-2">
                    <p className="font-medium text-slate-900">{item.label}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-slate-400">{item.image_type}</p>
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-600">{item.processing_chain}</td>
                  <td className="px-3 py-2">
                    <Badge variant="outline" className={cn("border text-[10px]", item.suitable_for_csv ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-500")}>
                      {item.suitable_for_csv ? "可导出" : "不适合"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant="outline" className={cn("border text-[10px]", item.requires_review ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-white text-slate-500")}>
                      {item.requires_review ? "需要" : "低"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    {stat && stat.total > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        <Badge variant="outline" className="border-slate-200 bg-slate-50 text-[10px] text-slate-600">{stat.total} 图</Badge>
                        {stat.accepted ? <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-700">{stat.accepted} 已标定</Badge> : null}
                        {stat.review_required ? <Badge variant="outline" className="border-amber-200 bg-amber-50 text-[10px] text-amber-700">{stat.review_required} 复核</Badge> : null}
                        {stat.skipped ? <Badge variant="outline" className="border-slate-200 bg-white text-[10px] text-slate-500">{stat.skipped} 跳过</Badge> : null}
                        {stat.failed ? <Badge variant="outline" className="border-red-200 bg-red-50 text-[10px] text-red-600">{stat.failed} 失败</Badge> : null}
                        {stat.row_count ? <Badge variant="outline" className="border-blue-200 bg-blue-50 text-[10px] text-blue-700">{stat.row_count} 点</Badge> : null}
                      </div>
                    ) : (
                      <span className="text-[11px] text-slate-400">-</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-500">{item.typical_content.slice(0, 3).join(" · ")}</td>
                      </>
                    );
                  })()}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function ResultBody({ data, jobId }: { data: StructuredExtractionResponse; jobId: number }) {
  const [showRaw, setShowRaw] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedResultIds, setSelectedResultIds] = useState<number[]>([]);
  const chartTypesQuery = useQuery({ queryKey: ["paper-chart-types"], queryFn: getPaperChartTypes });

  const hasFigures = data.figure_results.length > 0;
  const hasTables = data.table_results.length > 0;
  const hasText = data.text_results.length > 0;
  const hasPaperFigures = (data.paper_figures ?? []).length > 0;

  const totalSelected = selectedResultIds.length;
  const totalItems = data.figure_results.length + data.table_results.length + data.text_results.length;

  function toggleResult(resultId: number) {
    setSelectedResultIds(prev => prev.includes(resultId) ? prev.filter(id => id !== resultId) : [...prev, resultId]);
  }

  function selectAll() {
    const allIds = [
      ...data.figure_results.map(r => r.id),
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

      <ChartTypeMatrix items={chartTypesQuery.data ?? []} stats={data.chart_type_stats ?? []} />

      {hasPaperFigures ? <PaperFiguresGallery figures={data.paper_figures} /> : null}

      {hasFigures ? (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Image className="h-4 w-4 text-blue-500" />
            <h2 className="text-sm font-semibold text-slate-900">图片/图表分析结果</h2>
            <Badge variant="outline" className="text-[10px]">{data.figure_results.length}</Badge>
            {selectionMode && selectedResultIds.filter(id => data.figure_results.some(r => r.id === id)).length > 0 && (
              <Badge variant="outline" className="bg-blue-50 text-blue-600 text-[10px]">已选 {selectedResultIds.filter(id => data.figure_results.some(r => r.id === id)).length}</Badge>
            )}
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.figure_results.map((item, i) => (
              <FigureResultCard
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
