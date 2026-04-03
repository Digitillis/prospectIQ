// Copyright © 2026 ProspectIQ. All rights reserved.
// Authors: Avanish Mehrotra & ProspectIQ Technical Team
"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  PenTool,
  Loader2,
  Copy,
  Check,
  RefreshCw,
  Sparkles,
  Archive,
  ChevronRight,
  AlertCircle,
  User,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://prospectiq-production-4848.up.railway.app";

const LINKEDIN_CHAR_LIMIT = 3000;

const CONTENT_TYPES = [
  { key: "linkedin_post", label: "LinkedIn Post" },
  { key: "short_article", label: "Short Article" },
  { key: "thread", label: "Thread" },
] as const;

type ContentTypeKey = (typeof CONTENT_TYPES)[number]["key"];

// ---------------------------------------------------------------------------
// API types
// ---------------------------------------------------------------------------

interface VoiceProfileData {
  profile_id: string;
  workspace_id: string;
  tone: string;
  avg_sentence_length: string;
  vocabulary_level: string;
  structural_patterns: string;
  signature_phrases: string[];
  calibrated_at: string | null;
  writing_samples: string[];
}

interface PostData {
  post_id: string;
  workspace_id: string;
  topic: string;
  content_type: string;
  generated_content: string;
  hook_line: string;
  word_count: number;
  status: string;
  created_at: string | null;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function getAuthHeader(): Promise<string | null> {
  try {
    const { supabase } = await import("@/lib/supabase");
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return session?.access_token ? `Bearer ${session.access_token}` : null;
  } catch {
    return null;
  }
}

async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const authHeader = await getAuthHeader();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (authHeader) headers["Authorization"] = authHeader;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

const fetchVoiceProfile = () =>
  apiFetch<{ profile: VoiceProfileData | null }>("/api/ghostwriting/voice-profile");

const calibrateVoice = (samples: string[]) =>
  apiFetch<{ profile: VoiceProfileData; message: string }>(
    "/api/ghostwriting/voice-profile/calibrate",
    { method: "POST", body: JSON.stringify({ samples }) }
  );

const generatePost = (payload: {
  topic: string;
  content_type: string;
  target_persona?: string;
  include_cta: boolean;
}) =>
  apiFetch<{ post: PostData }>("/api/ghostwriting/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });

const regeneratePost = (postId: string, feedback: string) =>
  apiFetch<{ post: PostData }>(`/api/ghostwriting/posts/${postId}/regenerate`, {
    method: "POST",
    body: JSON.stringify({ feedback }),
  });

const listPosts = () =>
  apiFetch<{ posts: PostData[]; count: number }>("/api/ghostwriting/posts");

const archivePost = (postId: string) =>
  apiFetch<{ message: string }>(`/api/ghostwriting/posts/${postId}`, {
    method: "DELETE",
  });

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ToneBadge({ tone }: { tone: string }) {
  const colors: Record<string, string> = {
    authoritative: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
    formal: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
    conversational: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
    inspiring: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  };
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        colors[tone] ?? "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
      )}
    >
      {tone}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300",
    published: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
    archived: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500",
  };
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[10px] font-medium capitalize",
        colors[status] ?? "bg-gray-100 text-gray-500"
      )}
    >
      {status}
    </span>
  );
}

function ContentTypeBadge({ type }: { type: string }) {
  const labels: Record<string, string> = {
    linkedin_post: "LinkedIn",
    short_article: "Article",
    thread: "Thread",
  };
  return (
    <span className="rounded-full bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 px-2 py-0.5 text-[10px] font-medium">
      {labels[type] ?? type}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function GhostwritingPage() {
  // Voice profile state
  const [profile, setProfile] = useState<VoiceProfileData | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  // Calibration state
  const [samplesText, setSamplesText] = useState("");
  const [calibrating, setCalibrating] = useState(false);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);

  // Generator state
  const [topic, setTopic] = useState("");
  const [contentType, setContentType] = useState<ContentTypeKey>("linkedin_post");
  const [targetPersona, setTargetPersona] = useState("");
  const [includeCta, setIncludeCta] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);

  // Current generated post
  const [currentPost, setCurrentPost] = useState<PostData | null>(null);
  const [copied, setCopied] = useState(false);

  // Feedback / regeneration
  const [feedback, setFeedback] = useState("");
  const [regenerating, setRegenerating] = useState(false);

  // Post library
  const [posts, setPosts] = useState<PostData[]>([]);
  const [postsLoading, setPostsLoading] = useState(true);

  // ---------------------------------------------------------------------------
  // Load voice profile and post library on mount
  // ---------------------------------------------------------------------------

  const loadProfile = useCallback(async () => {
    setProfileLoading(true);
    try {
      const res = await fetchVoiceProfile();
      setProfile(res.profile);
    } catch {
      // Silently ignore — show onboarding card
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const loadPosts = useCallback(async () => {
    setPostsLoading(true);
    try {
      const res = await listPosts();
      setPosts(res.posts ?? []);
    } catch {
      // Non-fatal
    } finally {
      setPostsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProfile();
    loadPosts();
  }, [loadProfile, loadPosts]);

  // ---------------------------------------------------------------------------
  // Calibration handler
  // ---------------------------------------------------------------------------

  const handleCalibrate = async () => {
    const samples = samplesText
      .split(/\n---\n/)
      .map((s) => s.trim())
      .filter(Boolean);

    if (samples.length === 0) {
      setCalibrationError("Paste at least one writing sample.");
      return;
    }
    if (samples.length > 5) {
      setCalibrationError("Maximum 5 samples (separate with --- on its own line).");
      return;
    }

    setCalibrating(true);
    setCalibrationError(null);
    try {
      const res = await calibrateVoice(samples);
      setProfile(res.profile);
      setSamplesText("");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Calibration failed.";
      setCalibrationError(message);
    } finally {
      setCalibrating(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Generation handler
  // ---------------------------------------------------------------------------

  const handleGenerate = async () => {
    if (!topic.trim()) {
      setGenerationError("Please enter a topic.");
      return;
    }
    setGenerating(true);
    setGenerationError(null);
    setCurrentPost(null);
    try {
      const res = await generatePost({
        topic: topic.trim(),
        content_type: contentType,
        target_persona: targetPersona.trim() || undefined,
        include_cta: includeCta,
      });
      setCurrentPost(res.post);
      await loadPosts();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Generation failed.";
      setGenerationError(message);
    } finally {
      setGenerating(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Regeneration handler
  // ---------------------------------------------------------------------------

  const handleRegenerate = async () => {
    if (!currentPost || !feedback.trim()) return;
    setRegenerating(true);
    try {
      const res = await regeneratePost(currentPost.post_id, feedback.trim());
      setCurrentPost(res.post);
      setFeedback("");
      await loadPosts();
    } catch {
      // Non-fatal — leave existing content
    } finally {
      setRegenerating(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Copy handler
  // ---------------------------------------------------------------------------

  const handleCopy = async () => {
    if (!currentPost) return;
    await navigator.clipboard.writeText(currentPost.generated_content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // ---------------------------------------------------------------------------
  // Archive handler
  // ---------------------------------------------------------------------------

  const handleArchive = async (postId: string) => {
    try {
      await archivePost(postId);
      setPosts((prev) => prev.filter((p) => p.post_id !== postId));
      if (currentPost?.post_id === postId) setCurrentPost(null);
    } catch {
      // Non-fatal
    }
  };

  // ---------------------------------------------------------------------------
  // Load post into editor
  // ---------------------------------------------------------------------------

  const loadPostIntoEditor = (post: PostData) => {
    setCurrentPost(post);
    setTopic(post.topic);
    setContentType(post.content_type as ContentTypeKey);
    setFeedback("");
  };

  // ---------------------------------------------------------------------------
  // Character count
  // ---------------------------------------------------------------------------

  const charCount = currentPost?.generated_content.length ?? 0;
  const overLimit = charCount > LINKEDIN_CHAR_LIMIT;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex h-full min-h-0 bg-gray-50 dark:bg-gray-950">
      {/* ── Left panel: Voice Setup ── */}
      <aside className="flex w-[300px] shrink-0 flex-col gap-4 overflow-y-auto border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
        {/* Header */}
        <div className="flex items-center gap-2">
          <PenTool className="h-4 w-4 text-blue-500" />
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Your Voice Profile
          </span>
        </div>

        {profileLoading ? (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading profile…
          </div>
        ) : profile ? (
          /* Profile card — calibrated */
          <div className="flex flex-col gap-3 rounded-lg border border-gray-200 dark:border-gray-700 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                Voice calibrated
              </span>
              {profile.calibrated_at && (
                <span className="text-[10px] text-gray-400">
                  {new Date(profile.calibrated_at).toLocaleDateString()}
                </span>
              )}
            </div>

            {/* Attributes */}
            <div className="flex flex-wrap gap-1.5">
              <ToneBadge tone={profile.tone} />
              <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400 capitalize">
                {profile.avg_sentence_length} sentences
              </span>
              <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400 capitalize">
                {profile.vocabulary_level} vocab
              </span>
              <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400 capitalize">
                {profile.structural_patterns.replace("_", " ")}
              </span>
            </div>

            {/* Signature phrases */}
            {profile.signature_phrases.length > 0 && (
              <div>
                <p className="mb-1 text-[10px] font-medium text-gray-500 dark:text-gray-500 uppercase tracking-wide">
                  Signature phrases
                </p>
                <ul className="flex flex-col gap-0.5">
                  {profile.signature_phrases.slice(0, 3).map((phrase, i) => (
                    <li
                      key={i}
                      className="text-[11px] text-gray-600 dark:text-gray-400 italic truncate"
                      title={phrase}
                    >
                      &ldquo;{phrase}&rdquo;
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recalibrate toggle */}
            <details className="group">
              <summary className="cursor-pointer text-[11px] text-blue-500 hover:text-blue-600 list-none">
                Recalibrate voice
              </summary>
              <div className="mt-2 flex flex-col gap-2">
                <textarea
                  value={samplesText}
                  onChange={(e) => setSamplesText(e.target.value)}
                  rows={5}
                  placeholder={"Paste 1–5 past posts here.\n\nSeparate multiple posts with:\n---"}
                  className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-2 py-1.5 text-xs text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
                />
                {calibrationError && (
                  <p className="text-[10px] text-red-500">{calibrationError}</p>
                )}
                <button
                  onClick={handleCalibrate}
                  disabled={calibrating}
                  className="flex items-center justify-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-3 py-1.5 text-xs font-medium text-white transition-colors"
                >
                  {calibrating && <Loader2 className="h-3 w-3 animate-spin" />}
                  {calibrating ? "Analysing…" : "Recalibrate"}
                </button>
              </div>
            </details>
          </div>
        ) : (
          /* Onboarding card — no profile yet */
          <div className="flex flex-col gap-3 rounded-lg border border-dashed border-blue-300 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/30 p-3">
            <div className="flex items-start gap-2">
              <Sparkles className="h-4 w-4 text-blue-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-xs font-semibold text-blue-800 dark:text-blue-200">
                  Teach us your writing style
                </p>
                <p className="mt-0.5 text-[11px] text-blue-600 dark:text-blue-400">
                  Paste 1–3 past LinkedIn posts you've written. The more authentic, the better the output.
                </p>
              </div>
            </div>

            <textarea
              value={samplesText}
              onChange={(e) => setSamplesText(e.target.value)}
              rows={6}
              placeholder={"Paste your past posts here.\n\nSeparate multiple posts with a line containing only:\n---"}
              className="w-full rounded-md border border-blue-200 dark:border-blue-800 bg-white dark:bg-gray-900 px-2 py-1.5 text-xs text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
            />

            <p className="text-[10px] text-blue-500 dark:text-blue-400 italic">
              Paste real posts you've written — the more authentic, the better the output.
            </p>

            {calibrationError && (
              <p className="text-[10px] text-red-500">{calibrationError}</p>
            )}

            <button
              onClick={handleCalibrate}
              disabled={calibrating || !samplesText.trim()}
              className="flex items-center justify-center gap-1.5 rounded-md bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-3 py-2 text-xs font-semibold text-white transition-colors"
            >
              {calibrating && <Loader2 className="h-3 w-3 animate-spin" />}
              {calibrating ? "Analysing your style…" : "Calibrate Voice"}
            </button>
          </div>
        )}
      </aside>

      {/* ── Center panel: Generator ── */}
      <main className="flex flex-1 flex-col min-h-0 overflow-y-auto p-6 gap-5">
        {/* Topic */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-gray-700 dark:text-gray-300">
            What do you want to write about?
          </label>
          <textarea
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            rows={2}
            placeholder="e.g. Why manufacturers are leaving OEE dashboards behind"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        {/* Content type */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-gray-700 dark:text-gray-300">
            Content type
          </label>
          <div className="flex gap-2">
            {CONTENT_TYPES.map((ct) => (
              <button
                key={ct.key}
                onClick={() => setContentType(ct.key)}
                className={cn(
                  "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                  contentType === ct.key
                    ? "border-blue-500 bg-blue-600 text-white"
                    : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 hover:border-blue-400 hover:text-blue-600 dark:hover:text-blue-400"
                )}
              >
                {ct.label}
              </button>
            ))}
          </div>
        </div>

        {/* Target audience */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-gray-700 dark:text-gray-300">
            Who is this for?{" "}
            <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={targetPersona}
            onChange={(e) => setTargetPersona(e.target.value)}
            placeholder="e.g. plant managers, VP of Operations"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* CTA toggle */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setIncludeCta(!includeCta)}
            className={cn(
              "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
              includeCta ? "bg-blue-600" : "bg-gray-200 dark:bg-gray-700"
            )}
          >
            <span
              className={cn(
                "inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform",
                includeCta ? "translate-x-4" : "translate-x-1"
              )}
            />
          </button>
          <span className="text-xs text-gray-600 dark:text-gray-400">
            Include call-to-action?
          </span>
        </div>

        {/* Generate button */}
        <button
          onClick={handleGenerate}
          disabled={generating || !topic.trim()}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 py-2.5 text-sm font-semibold text-white transition-colors"
        >
          {generating ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              Generate Post
            </>
          )}
        </button>

        {generationError && (
          <div className="flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 p-3">
            <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
            <p className="text-xs text-red-600 dark:text-red-400">{generationError}</p>
          </div>
        )}

        {/* Generated content preview */}
        {currentPost && (
          <div className="flex flex-col gap-3">
            {/* LinkedIn post frame */}
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm">
              {/* Post header */}
              <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/40">
                  <User className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-gray-900 dark:text-gray-100">You</p>
                  <p className="text-[10px] text-gray-400">Just now · LinkedIn</p>
                </div>
              </div>

              {/* Post body */}
              <div className="px-4 py-3">
                <p className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap leading-relaxed">
                  {currentPost.generated_content}
                </p>
              </div>

              {/* Engagement bar */}
              <div className="flex items-center gap-4 border-t border-gray-100 dark:border-gray-800 px-4 py-2">
                <span className="text-[10px] text-gray-400">👍 Like</span>
                <span className="text-[10px] text-gray-400">💬 Comment</span>
                <span className="text-[10px] text-gray-400">🔁 Repost</span>
                <span className="text-[10px] text-gray-400">✉ Send</span>
              </div>
            </div>

            {/* Character count + platform limit */}
            <div className="flex items-center justify-between text-[11px]">
              <span
                className={cn(
                  "font-medium",
                  overLimit ? "text-red-500" : "text-gray-400"
                )}
              >
                {charCount.toLocaleString()} / {LINKEDIN_CHAR_LIMIT.toLocaleString()} chars
                {overLimit && " — over LinkedIn limit"}
              </span>
              <span className="text-gray-400">{currentPost.word_count} words</span>
            </div>

            {/* Action row */}
            <div className="flex items-center gap-2">
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                {copied ? (
                  <>
                    <Check className="h-3 w-3 text-green-500" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" />
                    Copy
                  </>
                )}
              </button>
            </div>

            {/* Feedback / regenerate */}
            <div className="flex gap-2">
              <input
                type="text"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleRegenerate()}
                placeholder='Tell me what to change… e.g. "make it shorter"'
                className="flex-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                onClick={handleRegenerate}
                disabled={regenerating || !feedback.trim()}
                className="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 transition-colors"
              >
                {regenerating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Regenerate
              </button>
            </div>
          </div>
        )}
      </main>

      {/* ── Right panel: Content Library ── */}
      <aside className="flex w-[280px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Past Posts
          </span>
          <span className="text-[11px] text-gray-400 tabular-nums">
            {posts.length}
          </span>
        </div>

        {postsLoading ? (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading…
          </div>
        ) : posts.length === 0 ? (
          <p className="text-[11px] text-gray-400 italic">
            No posts yet. Generate your first one!
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {posts.map((post) => (
              <li
                key={post.post_id}
                className={cn(
                  "group relative flex flex-col gap-1 rounded-lg border p-2.5 cursor-pointer transition-colors",
                  currentPost?.post_id === post.post_id
                    ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-950/30"
                    : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800/50"
                )}
                onClick={() => loadPostIntoEditor(post)}
              >
                {/* Hook line */}
                <p className="text-[11px] font-medium text-gray-800 dark:text-gray-200 line-clamp-2 pr-4">
                  {post.hook_line || post.generated_content.slice(0, 80)}
                </p>

                {/* Meta row */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  <ContentTypeBadge type={post.content_type} />
                  <StatusBadge status={post.status} />
                  {post.created_at && (
                    <span className="text-[10px] text-gray-400">
                      {new Date(post.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>

                {/* Archive button — shown on hover */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleArchive(post.post_id);
                  }}
                  title="Archive post"
                  className="absolute right-2 top-2 hidden group-hover:flex items-center justify-center rounded p-0.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                >
                  <Archive className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
