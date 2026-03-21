"use client";
import { useState, useEffect } from "react";

export interface Reminder {
  id: string;
  companyId: string;
  companyName: string;
  note: string;
  dueDate: string;
  createdAt: string;
}

export function useReminders() {
  const [reminders, setReminders] = useState<Reminder[]>(() => {
    if (typeof window === "undefined") return [];
    const stored = localStorage.getItem("prospectiq-reminders");
    return stored ? JSON.parse(stored) : [];
  });

  useEffect(() => {
    localStorage.setItem("prospectiq-reminders", JSON.stringify(reminders));
  }, [reminders]);

  const addReminder = (companyId: string, companyName: string, note: string, daysFromNow: number) => {
    const due = new Date();
    due.setDate(due.getDate() + daysFromNow);
    const reminder: Reminder = {
      id: Date.now().toString(),
      companyId,
      companyName,
      note,
      dueDate: due.toISOString(),
      createdAt: new Date().toISOString(),
    };
    setReminders(prev => [...prev, reminder]);
    return reminder;
  };

  const dismissReminder = (id: string) => {
    setReminders(prev => prev.filter(r => r.id !== id));
  };

  const dueReminders = reminders.filter(r => new Date(r.dueDate) <= new Date());
  const upcomingReminders = reminders.filter(r => new Date(r.dueDate) > new Date())
    .sort((a, b) => new Date(a.dueDate).getTime() - new Date(b.dueDate).getTime());

  return { reminders, dueReminders, upcomingReminders, addReminder, dismissReminder };
}
