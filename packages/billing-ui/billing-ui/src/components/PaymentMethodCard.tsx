/**
 * PaymentMethodCard — reusable payment method display.
 * Dependencies: Tailwind CSS, lucide-react.
 */

"use client";

import { CreditCard, Building2, AlertTriangle } from "lucide-react";
import type { PaymentMethod } from "../types";
import {
  paymentMethodLabel,
  paymentMethodExpiry,
  isCardExpiringSoon,
} from "../utils";

interface PaymentMethodCardProps {
  paymentMethod: PaymentMethod | null;
  onUpdate: () => void;    // Typically opens Stripe Customer Portal
  isUpdating?: boolean;
  accentClass?: string;    // Tailwind text color for the action button
}

export function PaymentMethodCard({
  paymentMethod,
  onUpdate,
  isUpdating = false,
  accentClass = "text-blue-600 dark:text-blue-400",
}: PaymentMethodCardProps) {
  const expirySoon = paymentMethod ? isCardExpiringSoon(paymentMethod) : false;
  const expiry = paymentMethod ? paymentMethodExpiry(paymentMethod) : null;

  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-gray-100 dark:bg-gray-800 p-2">
          {paymentMethod?.type === "us_bank_account" ? (
            <Building2 className="h-4 w-4 text-gray-500 dark:text-gray-400" />
          ) : (
            <CreditCard className="h-4 w-4 text-gray-500 dark:text-gray-400" />
          )}
        </div>
        {paymentMethod ? (
          <div>
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {paymentMethodLabel(paymentMethod)}
            </p>
            {expiry && (
              <p className={`text-xs mt-0.5 ${expirySoon ? "text-amber-600 dark:text-amber-400" : "text-gray-500 dark:text-gray-400"}`}>
                {expirySoon && <AlertTriangle className="inline h-3 w-3 mr-1 -mt-0.5" />}
                {expiry}
              </p>
            )}
            {paymentMethod.type === "us_bank_account" && paymentMethod.bank?.account_type && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 capitalize">
                {paymentMethod.bank.account_type} account
              </p>
            )}
          </div>
        ) : (
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">No payment method on file</p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
              Add a card or bank account to enable billing.
            </p>
          </div>
        )}
      </div>
      <button
        onClick={onUpdate}
        disabled={isUpdating}
        className={`shrink-0 text-sm font-medium hover:underline disabled:opacity-50 ${accentClass}`}
      >
        {isUpdating ? "Opening…" : paymentMethod ? "Update" : "Add"}
      </button>
    </div>
  );
}
