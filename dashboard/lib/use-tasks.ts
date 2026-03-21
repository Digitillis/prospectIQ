"use client";

import { useState, useEffect, useCallback } from "react";

export interface Task {
  id: string;
  companyId?: string;
  companyName?: string;
  contactName?: string;
  title: string;
  description?: string;
  dueDate: string; // ISO date string "YYYY-MM-DD"
  completed: boolean;
  createdAt: string;
}

const STORAGE_KEY = "prospectiq-tasks";

function loadTasks(): Task[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveTasks(tasks: Task[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
}

export function useTasks() {
  const [tasks, setTasks] = useState<Task[]>([]);

  // Load on mount (client only)
  useEffect(() => {
    setTasks(loadTasks());
  }, []);

  const persist = useCallback((next: Task[]) => {
    saveTasks(next);
    setTasks(next);
  }, []);

  const addTask = useCallback(
    (data: Omit<Task, "id" | "completed" | "createdAt">) => {
      const task: Task = {
        ...data,
        id: crypto.randomUUID(),
        completed: false,
        createdAt: new Date().toISOString(),
      };
      persist([...loadTasks(), task]);
    },
    [persist]
  );

  const completeTask = useCallback(
    (id: string) => {
      persist(
        loadTasks().map((t) =>
          t.id === id ? { ...t, completed: true } : t
        )
      );
    },
    [persist]
  );

  const uncompleteTask = useCallback(
    (id: string) => {
      persist(
        loadTasks().map((t) =>
          t.id === id ? { ...t, completed: false } : t
        )
      );
    },
    [persist]
  );

  const deleteTask = useCallback(
    (id: string) => {
      persist(loadTasks().filter((t) => t.id !== id));
    },
    [persist]
  );

  const today = new Date().toISOString().slice(0, 10);

  const activeTasks = tasks.filter((t) => !t.completed).sort(
    (a, b) => a.dueDate.localeCompare(b.dueDate)
  );
  const completedTasks = tasks
    .filter((t) => t.completed)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  const overdueTasks = activeTasks.filter((t) => t.dueDate < today);
  const todayTasks = activeTasks.filter((t) => t.dueDate === today);
  const upcomingTasks = activeTasks.filter((t) => t.dueDate > today);

  return {
    tasks,
    activeTasks,
    completedTasks,
    overdueTasks,
    todayTasks,
    upcomingTasks,
    addTask,
    completeTask,
    uncompleteTask,
    deleteTask,
  };
}
