"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Building2,
  ExternalLink,
  Heart,
  Linkedin,
  Loader2,
  Mail,
  Phone,
  Save,
  Snowflake,
  ThermometerSun,
  User,
  Pencil,
  X,
  MessageSquare,
  StickyNote,
  Star,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { getContact, updateContact, type Contact, type Interaction } from "@/lib/api";
import { cn, formatDate, formatTimeAgo, STATUS_COLORS } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContactDetail = Contact & {
  interactions?: Interaction[];
  companies?: {
    id: string;
    name: string;
    tier?: string;
    status: string;
    pqs_total: number;
    domain?: string;
  };
};

// ---------------------------------------------------------------------------
// Relationship strength helpers
// ---------------------------------------------------------------------------

function getRelationshipZone(score: number): {
  label: string;
  color: string;
  trackColor: string;
  icon: React.ReactNode;
  description: string;
} {
  if (score >= 70) {
    return {
      label: "Strong",
      color: "text-emerald-600",
      trackColor: "bg-emerald-500",
      icon: <Heart className="w-4 h-4" />,
      description: "Active relationship — high engagement",
    };
  }
  if (score >= 30) {
    return {
      label: "Warm",
      color: "text-amber-600",
      trackColor: "bg-amber-400",
      icon: <ThermometerSun className="w-4 h-4" />,
      description: "Some engagement — worth nurturing",
    };
  }
  return {
    label: "Cold",
    color: "text-blue-500",
    trackColor: "bg-blue-400",
    icon: <Snowflake className="w-4 h-4" />,
    description: "No meaningful engagement yet",
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FieldRow({
  label,
  value,
  editing,
  name,
  draft,
  setDraft,
  type = "text",
}: {
  label: string;
  value?: string;
  editing: boolean;
  name: string;
  draft: Record<string, unknown>;
  setDraft: (d: Record<string, unknown>) => void;
  type?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">{label}</span>
      {editing ? (
        <input
          type={type}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
          value={(draft[name] as string) ?? ""}
          onChange={(e) =>
            setDraft({ ...draft, [name]: e.target.value })
          }
          placeholder={`Enter ${label.toLowerCase()}`}
        />
      ) : (
        <span className={cn("text-sm", value ? "text-gray-800" : "text-gray-400 italic")}>
          {value || "—"}
        </span>
      )}
    </div>
  );
}

function InteractionItem({ item }: { item: Interaction }) {
  const iconMap: Record<string, React.ReactNode> = {
    note:          <StickyNote className="w-3.5 h-3.5 text-amber-500" />,
    email:         <Mail className="w-3.5 h-3.5 text-blue-500" />,
    call:          <Phone className="w-3.5 h-3.5 text-green-500" />,
    status_change: <CheckCircle2 className="w-3.5 h-3.5 text-purple-500" />,
    meeting:       <MessageSquare className="w-3.5 h-3.5 text-indigo-500" />,
  };
  const icon = iconMap[item.type] ?? <AlertCircle className="w-3.5 h-3.5 text-gray-400" />;

  return (
    <div className="flex gap-3 py-3 border-b border-gray-50 last:border-0">
      <div className="mt-0.5 flex-shrink-0 w-6 h-6 rounded-full bg-gray-50 flex items-center justify-center">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        {item.subject && (
          <p className="text-sm font-medium text-gray-800 truncate">{item.subject}</p>
        )}
        {item.body && (
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{item.body}</p>
        )}
        <p className="text-xs text-gray-400 mt-1">{formatTimeAgo(item.created_at)}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [contact, setContact] = useState<ContactDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Editable text fields
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  // Relationship strength — tracked separately for the slider UX
  const [relStrength, setRelStrength] = useState(0);
  const [relDirty, setRelDirty] = useState(false);

  const fetchContact = useCallback(async () => {
    try {
      const res = await getContact(id);
      setContact(res.data);
      const rs = res.data.relationship_strength ?? 0;
      setRelStrength(rs);
      setDraft({
        full_name:        res.data.full_name ?? "",
        email:            res.data.email ?? "",
        phone:            res.data.phone ?? "",
        title:            res.data.title ?? "",
        seniority:        res.data.seniority ?? "",
        department:       res.data.department ?? "",
        linkedin_url:     res.data.linkedin_url ?? "",
        persona_type:     res.data.persona_type ?? "",
        is_decision_maker: res.data.is_decision_maker ?? false,
        last_interaction_note: res.data.last_interaction_note ?? "",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load contact");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchContact();
  }, [fetchContact]);

  const handleSave = async () => {
    if (!contact) return;
    setSaving(true);
    setSaveSuccess(false);
    try {
      const payload: Record<string, unknown> = {};
      // Only include fields that differ from original
      const fields = ["full_name", "email", "phone", "title", "seniority",
                      "department", "linkedin_url", "persona_type", "is_decision_maker",
                      "last_interaction_note"] as const;
      for (const f of fields) {
        const original = contact[f as keyof ContactDetail];
        if (draft[f] !== undefined && draft[f] !== (original ?? "")) {
          payload[f] = draft[f];
        }
      }
      if (relDirty) {
        payload.relationship_strength = relStrength;
      }
      if (Object.keys(payload).length > 0) {
        await updateContact(id, payload);
      }
      setEditMode(false);
      setRelDirty(false);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
      fetchContact();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (!contact) return;
    setEditMode(false);
    setRelStrength(contact.relationship_strength ?? 0);
    setRelDirty(false);
    setDraft({
      full_name:        contact.full_name ?? "",
      email:            contact.email ?? "",
      phone:            contact.phone ?? "",
      title:            contact.title ?? "",
      seniority:        contact.seniority ?? "",
      department:       contact.department ?? "",
      linkedin_url:     contact.linkedin_url ?? "",
      persona_type:     contact.persona_type ?? "",
      is_decision_maker: contact.is_decision_maker ?? false,
      last_interaction_note: contact.last_interaction_note ?? "",
    });
  };

  // -------------------------------------------------------------------------
  // Render states
  // -------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
      </div>
    );
  }

  if (error || !contact) {
    return (
      <div className="p-8 text-center">
        <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
        <p className="text-gray-600">{error ?? "Contact not found"}</p>
        <Link href="/contacts" className="mt-4 inline-flex items-center gap-1 text-blue-600 text-sm hover:underline">
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Contacts
        </Link>
      </div>
    );
  }

  const zone = getRelationshipZone(relStrength);
  const company = contact.companies;
  const logoUrl = company?.domain
    ? `https://logo.clearbit.com/${company.domain}`
    : null;

  // -------------------------------------------------------------------------
  // Main render
  // -------------------------------------------------------------------------

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* Back nav */}
        <Link
          href="/contacts"
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 mb-6 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Contacts
        </Link>

        {/* Save success banner */}
        {saveSuccess && (
          <div className="mb-4 flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg px-4 py-2.5 text-sm">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            Contact saved successfully
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* ================================================================
              LEFT COLUMN — Contact identity + relationship strength
          ================================================================ */}
          <div className="lg:col-span-1 flex flex-col gap-5">

            {/* Identity card */}
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              {/* Avatar + name */}
              <div className="flex items-start gap-4 mb-5">
                <div className="w-14 h-14 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center flex-shrink-0">
                  <User className="w-7 h-7 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <h1 className="text-xl font-semibold text-gray-900 leading-tight">
                    {contact.full_name || "Unknown Contact"}
                  </h1>
                  {contact.title && (
                    <p className="text-sm text-gray-500 mt-0.5">{contact.title}</p>
                  )}
                  {contact.is_decision_maker && (
                    <span className="inline-flex items-center gap-1 mt-1.5 text-xs font-medium text-amber-700 bg-amber-50 rounded-full px-2.5 py-0.5">
                      <Star className="w-3 h-3" /> Decision Maker
                    </span>
                  )}
                </div>
              </div>

              {/* Company link */}
              {company && (
                <Link
                  href={`/prospects/${company.id}`}
                  className="flex items-center gap-3 p-3 rounded-xl bg-gray-50 hover:bg-blue-50 transition-colors group mb-5"
                >
                  {logoUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={logoUrl}
                      alt={company.name}
                      className="w-8 h-8 rounded object-contain"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = "none";
                      }}
                    />
                  ) : (
                    <Building2 className="w-5 h-5 text-gray-400 flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 group-hover:text-blue-700 truncate">
                      {company.name}
                    </p>
                    {company.tier && (
                      <p className="text-xs text-gray-400">Tier {company.tier}</p>
                    )}
                  </div>
                  <ExternalLink className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500 flex-shrink-0" />
                </Link>
              )}

              {/* Quick contact links */}
              <div className="flex flex-col gap-2">
                {contact.email && (
                  <a
                    href={`mailto:${contact.email}`}
                    className="flex items-center gap-2.5 text-sm text-gray-600 hover:text-blue-600 transition-colors"
                  >
                    <Mail className="w-4 h-4 text-gray-400" />
                    <span className="truncate">{contact.email}</span>
                  </a>
                )}
                {contact.phone && (
                  <a
                    href={`tel:${contact.phone}`}
                    className="flex items-center gap-2.5 text-sm text-gray-600 hover:text-blue-600 transition-colors"
                  >
                    <Phone className="w-4 h-4 text-gray-400" />
                    {contact.phone}
                  </a>
                )}
                {contact.linkedin_url && (
                  <a
                    href={contact.linkedin_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2.5 text-sm text-blue-600 hover:text-blue-800 transition-colors"
                  >
                    <Linkedin className="w-4 h-4" />
                    LinkedIn Profile
                    <ExternalLink className="w-3 h-3 text-gray-400 ml-auto" />
                  </a>
                )}
              </div>
            </div>

            {/* ============================================================
                RELATIONSHIP STRENGTH CARD
            ============================================================ */}
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-gray-700">Relationship Strength</h2>
                {!editMode && (
                  <button
                    onClick={() => setEditMode(true)}
                    className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1 transition-colors"
                  >
                    <Pencil className="w-3 h-3" /> Adjust
                  </button>
                )}
              </div>

              {/* Score display */}
              <div className={cn("flex items-center gap-2 mb-3", zone.color)}>
                {zone.icon}
                <span className="text-3xl font-bold tabular-nums">{relStrength}</span>
                <span className="text-sm font-medium ml-1">{zone.label}</span>
              </div>
              <p className="text-xs text-gray-400 mb-4">{zone.description}</p>

              {/* Three-zone visual bar */}
              <div className="relative mb-4">
                {/* Zone labels */}
                <div className="flex justify-between text-xs text-gray-400 mb-1">
                  <span>Cold</span>
                  <span>Warm</span>
                  <span>Strong</span>
                </div>
                {/* Track */}
                <div className="relative h-2 rounded-full overflow-hidden bg-gray-100">
                  {/* Zone coloring */}
                  <div
                    className="absolute inset-0 flex"
                    style={{ pointerEvents: "none" }}
                  >
                    <div className="h-full bg-blue-200" style={{ width: "30%" }} />
                    <div className="h-full bg-amber-200" style={{ width: "40%" }} />
                    <div className="h-full bg-emerald-200" style={{ width: "30%" }} />
                  </div>
                  {/* Filled portion */}
                  <div
                    className={cn("absolute inset-y-0 left-0 transition-all duration-200", zone.trackColor)}
                    style={{ width: `${relStrength}%` }}
                  />
                </div>
                {/* Zone boundary ticks */}
                <div className="flex justify-between text-xs text-gray-300 mt-0.5 px-px">
                  <span>0</span>
                  <span className="ml-[22%]">30</span>
                  <span className="ml-[28%]">70</span>
                  <span>100</span>
                </div>
              </div>

              {/* Slider — always visible, requires edit mode for mouse/touch */}
              <div className="relative">
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={relStrength}
                  disabled={!editMode}
                  onChange={(e) => {
                    setRelStrength(Number(e.target.value));
                    setRelDirty(true);
                  }}
                  className={cn(
                    "w-full h-1 rounded-full appearance-none cursor-pointer",
                    "accent-blue-600",
                    !editMode && "opacity-40 cursor-not-allowed"
                  )}
                  style={{
                    background: `linear-gradient(to right, #3b82f6 0%, #3b82f6 ${relStrength}%, #e5e7eb ${relStrength}%, #e5e7eb 100%)`,
                  }}
                />
              </div>

              {/* Zone legend chips */}
              <div className="flex gap-2 mt-4">
                {[
                  { label: "Cold", range: "0–29",  bg: "bg-blue-50",    text: "text-blue-600" },
                  { label: "Warm", range: "30–69",  bg: "bg-amber-50",   text: "text-amber-600" },
                  { label: "Strong", range: "70–100", bg: "bg-emerald-50", text: "text-emerald-600" },
                ].map((z) => (
                  <div
                    key={z.label}
                    className={cn("flex-1 rounded-lg px-2 py-1.5 text-center", z.bg)}
                  >
                    <p className={cn("text-xs font-semibold", z.text)}>{z.label}</p>
                    <p className="text-xs text-gray-400">{z.range}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ================================================================
              RIGHT COLUMN — Details + interactions
          ================================================================ */}
          <div className="lg:col-span-2 flex flex-col gap-5">

            {/* Details card */}
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-base font-semibold text-gray-800">Contact Details</h2>
                <div className="flex items-center gap-2">
                  {editMode ? (
                    <>
                      <button
                        onClick={handleCancel}
                        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 transition-colors"
                      >
                        <X className="w-3.5 h-3.5" /> Cancel
                      </button>
                      <button
                        onClick={handleSave}
                        disabled={saving}
                        className="inline-flex items-center gap-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-lg px-3 py-1.5 transition-colors disabled:opacity-60"
                      >
                        {saving ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Save className="w-3.5 h-3.5" />
                        )}
                        Save
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setEditMode(true)}
                      className="inline-flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-200 rounded-lg px-3 py-1.5 transition-colors"
                    >
                      <Pencil className="w-3.5 h-3.5" /> Edit
                    </button>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <FieldRow label="Full Name"   value={contact.full_name}   name="full_name"   editing={editMode} draft={draft} setDraft={setDraft} />
                <FieldRow label="Email"        value={contact.email}       name="email"       editing={editMode} draft={draft} setDraft={setDraft} type="email" />
                <FieldRow label="Phone"        value={contact.phone}       name="phone"       editing={editMode} draft={draft} setDraft={setDraft} type="tel" />
                <FieldRow label="Title"        value={contact.title}       name="title"       editing={editMode} draft={draft} setDraft={setDraft} />
                <FieldRow label="Seniority"    value={contact.seniority}   name="seniority"   editing={editMode} draft={draft} setDraft={setDraft} />
                <FieldRow label="Department"   value={contact.department}  name="department"  editing={editMode} draft={draft} setDraft={setDraft} />
                <FieldRow label="Persona Type" value={contact.persona_type} name="persona_type" editing={editMode} draft={draft} setDraft={setDraft} />
                <FieldRow label="LinkedIn URL" value={contact.linkedin_url} name="linkedin_url" editing={editMode} draft={draft} setDraft={setDraft} />
              </div>

              {/* Decision maker toggle */}
              <div className="mt-5 pt-5 border-t border-gray-50">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-700">Decision Maker</p>
                    <p className="text-xs text-gray-400">
                      This contact has purchasing or approval authority
                    </p>
                  </div>
                  {editMode ? (
                    <button
                      onClick={() => setDraft({ ...draft, is_decision_maker: !draft.is_decision_maker })}
                      className={cn(
                        "relative inline-flex h-5 w-9 rounded-full transition-colors duration-200 focus:outline-none",
                        draft.is_decision_maker ? "bg-blue-600" : "bg-gray-200"
                      )}
                    >
                      <span
                        className={cn(
                          "inline-block w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 mt-0.5",
                          draft.is_decision_maker ? "translate-x-4" : "translate-x-0.5"
                        )}
                      />
                    </button>
                  ) : (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-xs font-medium rounded-full px-2.5 py-0.5",
                        contact.is_decision_maker
                          ? "bg-amber-50 text-amber-700"
                          : "bg-gray-100 text-gray-500"
                      )}
                    >
                      {contact.is_decision_maker ? (
                        <><Star className="w-3 h-3" /> Yes</>
                      ) : "No"}
                    </span>
                  )}
                </div>
              </div>

              {/* Last interaction note */}
              <div className="mt-5 pt-5 border-t border-gray-50">
                <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                  Last Interaction Note
                </p>
                {editMode ? (
                  <textarea
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white resize-none"
                    rows={3}
                    value={(draft.last_interaction_note as string) ?? ""}
                    onChange={(e) => setDraft({ ...draft, last_interaction_note: e.target.value })}
                    placeholder="Add a note about the last interaction..."
                  />
                ) : (
                  <p className={cn("text-sm", contact.last_interaction_note ? "text-gray-700" : "text-gray-400 italic")}>
                    {contact.last_interaction_note || "No note recorded"}
                  </p>
                )}
              </div>

              {/* Meta */}
              {contact.created_at && (
                <div className="mt-4 pt-4 border-t border-gray-50 flex gap-4 text-xs text-gray-400">
                  <span>Created {formatDate(contact.created_at)}</span>
                  {contact.updated_at && (
                    <span>Updated {formatTimeAgo(contact.updated_at)}</span>
                  )}
                  {contact.status && (
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 font-medium",
                        STATUS_COLORS[contact.status] ?? "bg-gray-100 text-gray-500"
                      )}
                    >
                      {contact.status}
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* ============================================================
                INTERACTIONS TIMELINE
            ============================================================ */}
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              <h2 className="text-base font-semibold text-gray-800 mb-1">Interaction History</h2>
              {company && (
                <p className="text-xs text-gray-400 mb-4">
                  Showing company-level interactions for{" "}
                  <Link
                    href={`/prospects/${company.id}`}
                    className="text-blue-500 hover:underline"
                  >
                    {company.name}
                  </Link>
                </p>
              )}

              {!contact.interactions || contact.interactions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-center">
                  <MessageSquare className="w-8 h-8 text-gray-200 mb-3" />
                  <p className="text-sm text-gray-400">No interactions recorded yet</p>
                  {company && (
                    <Link
                      href={`/prospects/${company.id}`}
                      className="mt-3 text-xs text-blue-500 hover:underline"
                    >
                      Go to company page to add a note
                    </Link>
                  )}
                </div>
              ) : (
                <div className="divide-y divide-gray-50">
                  {contact.interactions.map((item) => (
                    <InteractionItem key={item.id} item={item} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
