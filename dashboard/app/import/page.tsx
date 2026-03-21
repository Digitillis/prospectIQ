"use client";

import { useState, useCallback, useRef, DragEvent, ChangeEvent } from "react";
import Link from "next/link";
import {
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Download,
  Loader2,
} from "lucide-react";
import { importCompaniesCSV, ImportResult } from "@/lib/api";
import { cn } from "@/lib/utils";

const SAMPLE_CSV = `name,domain,website,industry,state,tier,employee_count,revenue_range
Acme Manufacturing,acme.com,https://acme.com,Metal Fabrication,TX,1,250,$10M-$50M
Beta Foods Inc,betafoods.com,,Food & Beverage,CA,2,80,$5M-$10M
Gamma Plastics,,https://gammaplastics.io,Plastics Manufacturing,OH,3,45,
`;

const EXPECTED_COLUMNS = [
  { name: "name", required: true, description: "Company name" },
  { name: "domain", required: false, description: "e.g. acme.com (used to detect duplicates)" },
  { name: "website", required: false, description: "Full URL" },
  { name: "industry", required: false, description: "e.g. Metal Fabrication" },
  { name: "state", required: false, description: "Two-letter state code or full name" },
  { name: "tier", required: false, description: "1, 2, or 3" },
  { name: "employee_count", required: false, description: "Integer" },
  { name: "revenue_range", required: false, description: "e.g. $10M-$50M" },
];

function parseCSVPreview(text: string): { headers: string[]; rows: string[][] } {
  const lines = text.trim().split("\n").slice(0, 6); // header + up to 5 rows
  if (lines.length === 0) return { headers: [], rows: [] };
  const headers = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
  const rows = lines.slice(1).map((line) =>
    line.split(",").map((cell) => cell.trim().replace(/^"|"$/g, ""))
  );
  return { headers, rows };
}

function downloadSampleCSV() {
  const blob = new Blob([SAMPLE_CSV], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "prospectiq_import_template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<{ headers: string[]; rows: string[][] } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    setFile(f);
    setResult(null);
    setImportError(null);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      setPreview(parseCSVPreview(text));
    };
    reader.readAsText(f);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      const dropped = e.dataTransfer.files[0];
      if (dropped && dropped.name.endsWith(".csv")) {
        handleFile(dropped);
      }
    },
    [handleFile]
  );

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (picked) handleFile(picked);
  };

  const handleImport = async () => {
    if (!file) return;
    setImporting(true);
    setImportError(null);
    setResult(null);
    try {
      const res = await importCompaniesCSV(file);
      setResult(res.data);
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImporting(false);
    }
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setImportError(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Bulk Import</h2>
          <p className="mt-1 text-sm text-gray-500">
            Import prospect companies from a CSV file
          </p>
        </div>
        <Link
          href="/prospects"
          className="text-sm text-digitillis-accent hover:underline"
        >
          ← Back to Prospects
        </Link>
      </div>

      {/* Result Banner */}
      {result && (
        <div
          className={cn(
            "rounded-xl border p-5",
            result.errors.length === 0
              ? "border-green-200 bg-green-50"
              : "border-amber-200 bg-amber-50"
          )}
        >
          <div className="flex items-center gap-2 mb-3">
            {result.errors.length === 0 ? (
              <CheckCircle2 className="h-5 w-5 text-green-600" />
            ) : (
              <AlertCircle className="h-5 w-5 text-amber-600" />
            )}
            <h3 className="font-semibold text-gray-900">Import Complete</h3>
          </div>
          <div className="flex gap-6 text-sm mb-3">
            <div>
              <span className="text-gray-500">Imported: </span>
              <span className="font-bold text-green-700">{result.imported}</span>
            </div>
            <div>
              <span className="text-gray-500">Skipped: </span>
              <span className="font-semibold text-gray-700">{result.skipped}</span>
            </div>
            <div>
              <span className="text-gray-500">Errors: </span>
              <span
                className={cn(
                  "font-semibold",
                  result.errors.length > 0 ? "text-red-600" : "text-gray-700"
                )}
              >
                {result.errors.length}
              </span>
            </div>
          </div>
          {result.errors.length > 0 && (
            <div className="space-y-1">
              {result.errors.map((err, i) => (
                <p key={i} className="text-xs text-red-700 font-mono">
                  {err}
                </p>
              ))}
            </div>
          )}
          <div className="mt-4 flex gap-3">
            <Link
              href="/prospects"
              className="rounded-md bg-digitillis-accent px-4 py-2 text-sm font-medium text-white hover:bg-digitillis-accent/90 transition-colors"
            >
              View Prospects
            </Link>
            <button
              onClick={reset}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Import Another File
            </button>
          </div>
        </div>
      )}

      {importError && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <XCircle className="h-4 w-4 shrink-0" />
          {importError}
        </div>
      )}

      {/* Drop Zone */}
      {!result && (
        <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            className={cn(
              "flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-12 text-center cursor-pointer transition-colors",
              dragging
                ? "border-digitillis-accent bg-digitillis-accent/5"
                : file
                ? "border-green-400 bg-green-50"
                : "border-gray-300 bg-gray-50 hover:border-digitillis-accent hover:bg-digitillis-accent/5"
            )}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={handleChange}
            />
            {file ? (
              <>
                <FileText className="h-10 w-10 text-green-500 mb-3" />
                <p className="font-medium text-gray-900">{file.name}</p>
                <p className="mt-1 text-sm text-gray-500">
                  {(file.size / 1024).toFixed(1)} KB · Click to change
                </p>
              </>
            ) : (
              <>
                <Upload className="h-10 w-10 text-gray-400 mb-3" />
                <p className="font-medium text-gray-700">
                  Drop a CSV file here, or click to browse
                </p>
                <p className="mt-1 text-sm text-gray-400">
                  Only .csv files are accepted
                </p>
              </>
            )}
          </div>
        </section>
      )}

      {/* Preview Table */}
      {preview && !result && (
        <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="text-base font-semibold text-gray-900 mb-4">
            Preview (first 5 rows)
          </h3>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  {preview.headers.map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left font-medium text-gray-600"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {preview.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} className="px-3 py-2 text-gray-700">
                        {cell || (
                          <span className="text-gray-300 italic">empty</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Import button */}
          <div className="mt-5 flex items-center justify-between">
            <button
              onClick={reset}
              className="text-sm text-gray-500 hover:text-gray-700 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleImport}
              disabled={importing}
              className="flex items-center gap-2 rounded-md bg-digitillis-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-digitillis-accent/90 disabled:opacity-60 transition-colors"
            >
              {importing ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Importing…
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  Import Companies
                </>
              )}
            </button>
          </div>
        </section>
      )}

      {/* Column Reference */}
      <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">
            Expected Columns
          </h3>
          <button
            onClick={downloadSampleCSV}
            className="flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <Download className="h-3.5 w-3.5" />
            Download Template
          </button>
        </div>
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-2.5 text-left font-medium text-gray-600">
                  Column
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-600">
                  Required
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-600">
                  Description
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {EXPECTED_COLUMNS.map((col) => (
                <tr key={col.name}>
                  <td className="px-4 py-2.5">
                    <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-800">
                      {col.name}
                    </code>
                  </td>
                  <td className="px-4 py-2.5">
                    {col.required ? (
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                        Required
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">Optional</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs">
                    {col.description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-gray-400">
          Duplicate companies (matched by domain) will be skipped automatically.
          All imported companies start with status <code className="rounded bg-gray-100 px-1 py-0.5">discovered</code>.
        </p>
      </section>
    </div>
  );
}
