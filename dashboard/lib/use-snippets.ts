"use client";

import { useState, useEffect, useCallback } from "react";

export interface Snippet {
  id: string;
  name: string;
  shortcut: string; // e.g. "/intro", "/cta"
  content: string;
}

const SNIPPETS_KEY = "prospectiq-snippets";
const MEETING_LINK_KEY = "prospectiq-meeting-link";

const DEFAULT_SNIPPETS: Snippet[] = [
  {
    id: "1",
    name: "Soft Intro",
    shortcut: "/intro",
    content: "I noticed your team at {company} is...",
  },
  {
    id: "2",
    name: "Pain Point Hook",
    shortcut: "/pain",
    content:
      "Many manufacturing leaders tell us their biggest challenge is...",
  },
  {
    id: "3",
    name: "CTA - Meeting",
    shortcut: "/cta",
    content:
      "Would it make sense to grab 15 minutes this week to explore?",
  },
  {
    id: "4",
    name: "CTA - Demo",
    shortcut: "/demo",
    content:
      "Happy to show you a quick demo of how this works for companies like {company}.",
  },
  {
    id: "5",
    name: "Social Proof",
    shortcut: "/proof",
    content:
      "We've helped similar manufacturers reduce unplanned downtime by 40%.",
  },
];

function loadSnippets(): Snippet[] {
  if (typeof window === "undefined") return DEFAULT_SNIPPETS;
  try {
    const stored = localStorage.getItem(SNIPPETS_KEY);
    if (!stored) return DEFAULT_SNIPPETS;
    return JSON.parse(stored);
  } catch {
    return DEFAULT_SNIPPETS;
  }
}

function saveSnippets(snippets: Snippet[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(SNIPPETS_KEY, JSON.stringify(snippets));
}

export function useSnippets() {
  const [snippets, setSnippets] = useState<Snippet[]>([]);

  useEffect(() => {
    setSnippets(loadSnippets());
  }, []);

  const persist = useCallback((next: Snippet[]) => {
    saveSnippets(next);
    setSnippets(next);
  }, []);

  const addSnippet = useCallback(
    (data: Omit<Snippet, "id">) => {
      const snippet: Snippet = { ...data, id: crypto.randomUUID() };
      persist([...loadSnippets(), snippet]);
    },
    [persist]
  );

  const updateSnippet = useCallback(
    (id: string, data: Partial<Omit<Snippet, "id">>) => {
      persist(
        loadSnippets().map((s) => (s.id === id ? { ...s, ...data } : s))
      );
    },
    [persist]
  );

  const deleteSnippet = useCallback(
    (id: string) => {
      persist(loadSnippets().filter((s) => s.id !== id));
    },
    [persist]
  );

  return { snippets, addSnippet, updateSnippet, deleteSnippet };
}

// ---------------------------------------------------------------------------
// Meeting link hook
// ---------------------------------------------------------------------------

export function useMeetingLink() {
  const [link, setLink] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return localStorage.getItem(MEETING_LINK_KEY) || "";
  });

  const save = useCallback((url: string) => {
    setLink(url);
    if (typeof window !== "undefined") {
      localStorage.setItem(MEETING_LINK_KEY, url);
    }
  }, []);

  return { link, save };
}
