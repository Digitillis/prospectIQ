/**
 * InvoiceTable — reusable invoice history table.
 * Dependencies: Tailwind CSS, lucide-react.
 */

"use client";

import { Download, ExternalLink, FileText } from "lucide-react";
import type { Invoice } from "../types";
import { fmtDate, fmtCurrency, invoiceStatusColor } from "../utils";

interface InvoiceTableProps {
  invoices: Invoice[];
}

export function InvoiceTable({ invoices }: InvoiceTableProps) {
  if (invoices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <FileText className="h-8 w-8 text-gray-300 dark:text-gray-600 mb-3" />
        <p className="text-sm text-gray-500 dark:text-gray-400">No invoices yet</p>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
          Invoices will appear here after your first payment.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 dark:border-gray-800">
            <th className="pb-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              Date
            </th>
            <th className="pb-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide pl-4">
              Description
            </th>
            <th className="pb-2 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              Amount
            </th>
            <th className="pb-2 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide px-4">
              Status
            </th>
            <th className="pb-2 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50 dark:divide-gray-800/50">
          {invoices.map((inv) => (
            <tr key={inv.id} className="group hover:bg-gray-50/50 dark:hover:bg-gray-800/30 transition-colors">
              <td className="py-3 text-gray-500 dark:text-gray-400 text-xs whitespace-nowrap">
                {fmtDate(inv.created)}
              </td>
              <td className="py-3 pl-4 text-gray-700 dark:text-gray-300 max-w-[240px] truncate">
                {inv.description}
                {inv.number && (
                  <span className="ml-1.5 text-xs text-gray-400 dark:text-gray-500">
                    #{inv.number}
                  </span>
                )}
              </td>
              <td className="py-3 text-right font-medium tabular-nums text-gray-900 dark:text-gray-100 whitespace-nowrap">
                {fmtCurrency(inv.status === "paid" ? inv.amount_paid : inv.amount_due, inv.currency)}
              </td>
              <td className="py-3 text-center px-4">
                <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${invoiceStatusColor(inv.status)}`}>
                  {inv.status === "paid" ? "Paid" :
                   inv.status === "open" ? "Open" :
                   inv.status === "draft" ? "Draft" :
                   inv.status === "void" ? "Void" :
                   inv.status === "uncollectible" ? "Uncollectible" :
                   inv.status}
                </span>
              </td>
              <td className="py-3 text-right">
                <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  {inv.invoice_pdf && (
                    <a
                      href={inv.invoice_pdf}
                      target="_blank"
                      rel="noreferrer"
                      className="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      title="Download PDF"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </a>
                  )}
                  {inv.hosted_invoice_url && (
                    <a
                      href={inv.hosted_invoice_url}
                      target="_blank"
                      rel="noreferrer"
                      className="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      title="View invoice"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
