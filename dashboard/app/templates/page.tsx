"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Mail,
  Linkedin,
  Phone,
  MessageSquare,
  Clock,
  FileText,
  Loader2,
  ChevronDown,
  ChevronUp,
  Hash,
  Type,
  AlignLeft,
  Zap,
} from "lucide-react";
import { getTemplates, type EmailTemplate } from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Channel helpers ──────────────────────────────────────────────────────────

type Channel = "email" | "linkedin" | "phone" | string;

function ChannelIcon({ channel, className }: { channel: Channel; className?: string }) {
  if (channel === "email") return <Mail className={cn("h-4 w-4", className)} />;
  if (channel === "linkedin") return <Linkedin className={cn("h-4 w-4", className)} />;
  if (channel === "phone") return <Phone className={cn("h-4 w-4", className)} />;
  return <MessageSquare className={cn("h-4 w-4", className)} />;
}

function channelLabel(channel: Channel) {
  if (channel === "email") return "Email";
  if (channel === "linkedin") return "LinkedIn";
  if (channel === "phone") return "Phone";
  return channel;
}

function channelColour(channel: Channel) {
  if (channel === "email")
    return "bg-blue-500/15 text-blue-400 border-blue-500/30";
  if (channel === "linkedin")
    return "bg-sky-500/15 text-sky-400 border-sky-500/30";
  if (channel === "phone")
    return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
  return "bg-slate-500/15 text-slate-400 border-slate-500/30";
}

// ─── Instruction field labels ─────────────────────────────────────────────────

const INSTRUCTION_META: Record<
  string,
  { label: string; icon: React.ElementType; order: number }
> = {
  subject_approach: { label: "Subject line", icon: Hash, order: 0 },
  body_approach: { label: "Body approach", icon: AlignLeft, order: 1 },
  approach: { label: "Approach", icon: AlignLeft, order: 1 },
  tone: { label: "Tone", icon: Zap, order: 2 },
  max_words: { label: "Max words", icon: Type, order: 3 },
  note: { label: "Note", icon: MessageSquare, order: 4 },
};

function InstructionRow({
  fieldKey,
  value,
}: {
  fieldKey: string;
  value: unknown;
}) {
  const meta = INSTRUCTION_META[fieldKey];
  const Icon = meta?.icon ?? FileText;
  const label = meta?.label ?? fieldKey.replace(/_/g, " ");

  if (fieldKey === "anti_patterns" && Array.isArray(value)) {
    return (
      <div className="flex gap-3">
        <div className="mt-0.5 shrink-0 text-slate-500">
          <Zap className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Anti-patterns
          </p>
          <ul className="space-y-1">
            {(value as string[]).map((ap, i) => (
              <li key={i} className="flex gap-1.5 text-xs text-slate-400">
                <span className="mt-0.5 shrink-0 text-red-500/70">✕</span>
                {ap}
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 shrink-0 text-slate-500">
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0">
        <p className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </p>
        {typeof value === "number" ? (
          <p className="text-sm font-semibold text-amber-400">{value} words</p>
        ) : (
          <p className="text-sm leading-relaxed text-slate-300">
            {String(value)}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Template card ────────────────────────────────────────────────────────────

function TemplateCard({
  template,
  isLast,
}: {
  template: EmailTemplate;
  isLast: boolean;
}) {
  const [open, setOpen] = useState(false);
  const hasInstructions = Object.keys(template.instructions).length > 0;

  // Sort instruction keys by our preferred order
  const sortedKeys = Object.keys(template.instructions).sort((a, b) => {
    const oa = INSTRUCTION_META[a]?.order ?? 99;
    const ob = INSTRUCTION_META[b]?.order ?? 99;
    return oa - ob;
  });

  return (
    <div className="relative flex gap-4">
      {/* Timeline spine */}
      <div className="flex flex-col items-center">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-bold",
            channelColour(template.channel)
          )}
        >
          <ChannelIcon channel={template.channel} />
        </div>
        {!isLast && (
          <div className="mt-1 w-px flex-1 bg-white/10" />
        )}
      </div>

      {/* Card body */}
      <div className={cn("mb-4 flex-1 rounded-xl border border-white/10 bg-white/5", open && "bg-white/[0.07]")}>
        {/* Header row */}
        <button
          onClick={() => setOpen((p) => !p)}
          disabled={!hasInstructions}
          className="flex w-full items-start gap-3 p-4 text-left"
        >
          <div className="flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
                  channelColour(template.channel)
                )}
              >
                <ChannelIcon channel={template.channel} />
                {channelLabel(template.channel)}
              </span>

              {template.delay_days > 0 && (
                <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                  <Clock className="h-3 w-3" />
                  +{template.delay_days}d
                </span>
              )}
              {template.delay_days === 0 && template.step > 1 && (
                <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                  <Clock className="h-3 w-3" />
                  Same day
                </span>
              )}
              {template.delay_days === 0 && template.step === 1 && (
                <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                  <Zap className="h-3 w-3" />
                  Day 0
                </span>
              )}
            </div>

            <p className="font-mono text-sm text-slate-200">
              {template.template_name}
            </p>

            {/* Inline preview — tone and max_words visible without expanding */}
            <div className="flex flex-wrap gap-3 pt-0.5">
              {!!template.instructions.tone && (
                <span className="text-xs text-slate-500">
                  Tone:{" "}
                  <span className="text-slate-400">
                    {String(template.instructions.tone)}
                  </span>
                </span>
              )}
              {!!template.instructions.max_words && (
                <span className="text-xs text-slate-500">
                  Max:{" "}
                  <span className="font-medium text-amber-400">
                    {String(template.instructions.max_words)} words
                  </span>
                </span>
              )}
            </div>
          </div>

          {hasInstructions && (
            <div className="mt-1 shrink-0 text-slate-500">
              {open ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </div>
          )}
        </button>

        {/* Expanded instructions */}
        {open && hasInstructions && (
          <div className="border-t border-white/10 px-4 pb-4 pt-3">
            <div className="space-y-4">
              {sortedKeys.map((key) => (
                <InstructionRow
                  key={key}
                  fieldKey={key}
                  value={template.instructions[key]}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Sequence group ───────────────────────────────────────────────────────────

function SequenceGroup({ seqName, templates }: { seqName: string; templates: EmailTemplate[] }) {
  const first = templates[0];

  // Count channels present in this sequence
  const channelCounts = templates.reduce<Record<string, number>>((acc, t) => {
    acc[t.channel] = (acc[t.channel] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
      {/* Sequence header */}
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-white">
            {first?.sequence_display_name ?? seqName}
          </h2>
          {first?.sequence_description && (
            <p className="mt-0.5 text-sm text-slate-400">
              {first.sequence_description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          {Object.entries(channelCounts).map(([ch, count]) => (
            <span
              key={ch}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs",
                channelColour(ch)
              )}
            >
              <ChannelIcon channel={ch} />
              {count} {channelLabel(ch)}
            </span>
          ))}
        </div>
      </div>

      {/* Template timeline */}
      <div>
        {templates.map((t, idx) => (
          <TemplateCard key={t.id} template={t} isLast={idx === templates.length - 1} />
        ))}
      </div>
    </section>
  );
}

// ─── Filter pill ──────────────────────────────────────────────────────────────

function FilterPill({
  label,
  active,
  onClick,
  icon: Icon,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  icon?: React.ElementType;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
        active
          ? "border-digitillis-accent/60 bg-digitillis-accent/20 text-white"
          : "border-white/10 bg-white/5 text-slate-400 hover:border-white/20 hover:text-white"
      )}
    >
      {Icon && <Icon className="h-3.5 w-3.5" />}
      {label}
    </button>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type FilterChannel = "all" | "email" | "linkedin" | "phone";

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterChannel>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getTemplates();
      setTemplates(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Apply channel filter
  const filtered =
    filter === "all" ? templates : templates.filter((t) => t.channel === filter);

  // Group by sequence name (preserving insertion order)
  const grouped: Record<string, EmailTemplate[]> = {};
  for (const t of filtered) {
    if (!grouped[t.sequence_name]) grouped[t.sequence_name] = [];
    grouped[t.sequence_name].push(t);
  }

  // Counts for filter pills
  const counts = templates.reduce<Record<string, number>>((acc, t) => {
    acc[t.channel] = (acc[t.channel] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex h-full flex-col">
      {/* Page header */}
      <div className="border-b border-white/10 px-6 py-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-digitillis-accent/20">
              <FileText className="h-5 w-5 text-digitillis-accent" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white">
                Email Template Library
              </h1>
              <p className="text-sm text-slate-400">
                Outreach templates and instructions for each sequence step
              </p>
            </div>
          </div>

          {!loading && !error && (
            <div className="text-sm text-slate-500">
              {templates.length} template{templates.length !== 1 ? "s" : ""} across{" "}
              {Object.keys(grouped).length === 0
                ? Object.keys(
                    templates.reduce<Record<string, boolean>>((a, t) => {
                      a[t.sequence_name] = true;
                      return a;
                    }, {})
                  ).length
                : Object.keys(grouped).length}{" "}
              sequence{Object.keys(grouped).length !== 1 ? "s" : ""}
            </div>
          )}
        </div>

        {/* Channel filter pills */}
        {!loading && !error && templates.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            <FilterPill
              label={`All (${templates.length})`}
              active={filter === "all"}
              onClick={() => setFilter("all")}
            />
            {(["email", "linkedin", "phone"] as const).map((ch) =>
              counts[ch] ? (
                <FilterPill
                  key={ch}
                  label={`${channelLabel(ch)} (${counts[ch]})`}
                  active={filter === ch}
                  onClick={() => setFilter(ch)}
                  icon={
                    ch === "email" ? Mail : ch === "linkedin" ? Linkedin : Phone
                  }
                />
              ) : null
            )}
          </div>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {loading && (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            Loading templates…
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-4 text-sm text-red-400">
            {error}
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 py-20 text-slate-500">
            <FileText className="h-8 w-8 opacity-40" />
            <p className="text-sm">
              {filter === "all"
                ? "No templates found."
                : `No ${channelLabel(filter)} templates in this sequence.`}
            </p>
          </div>
        )}

        {!loading && !error && Object.keys(grouped).length > 0 && (
          <div className="space-y-6">
            {Object.entries(grouped).map(([seqName, seqTemplates]) => (
              <SequenceGroup
                key={seqName}
                seqName={seqName}
                templates={seqTemplates}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
