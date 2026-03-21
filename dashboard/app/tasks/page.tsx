"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ListChecks,
  Plus,
  Trash2,
  CheckSquare,
  Square,
  AlertCircle,
  Clock,
  CalendarDays,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useTasks, type Task } from "@/lib/use-tasks";
import { cn } from "@/lib/utils";

function formatDate(dateStr: string) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function TaskCard({
  task,
  onComplete,
  onUncomplete,
  onDelete,
}: {
  task: Task;
  onComplete: (id: string) => void;
  onUncomplete: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border bg-white px-4 py-3 shadow-sm transition-opacity",
        task.completed && "opacity-50"
      )}
    >
      <button
        onClick={() =>
          task.completed ? onUncomplete(task.id) : onComplete(task.id)
        }
        className="mt-0.5 shrink-0 text-gray-400 hover:text-digitillis-accent transition-colors"
      >
        {task.completed ? (
          <CheckSquare className="h-5 w-5 text-green-500" />
        ) : (
          <Square className="h-5 w-5" />
        )}
      </button>

      <div className="min-w-0 flex-1">
        <p
          className={cn(
            "text-sm font-medium text-gray-900",
            task.completed && "line-through"
          )}
        >
          {task.title}
        </p>
        {task.description && (
          <p className="mt-0.5 text-xs text-gray-500 truncate">{task.description}</p>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {task.companyId ? (
            <Link
              href={`/prospects/${task.companyId}`}
              className="text-xs text-digitillis-accent hover:underline font-medium"
            >
              {task.companyName || "Company"}
            </Link>
          ) : task.companyName ? (
            <span className="text-xs text-gray-500">{task.companyName}</span>
          ) : null}
          {task.contactName && (
            <span className="text-xs text-gray-400">· {task.contactName}</span>
          )}
          <span className="text-xs text-gray-400">Due {formatDate(task.dueDate)}</span>
        </div>
      </div>

      <button
        onClick={() => onDelete(task.id)}
        className="mt-0.5 shrink-0 text-gray-300 hover:text-red-500 transition-colors"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}

function Section({
  title,
  icon: Icon,
  iconClass,
  tasks,
  emptyText,
  onComplete,
  onUncomplete,
  onDelete,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ElementType;
  iconClass: string;
  tasks: Task[];
  emptyText: string;
  onComplete: (id: string) => void;
  onUncomplete: (id: string) => void;
  onDelete: (id: string) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 mb-3 text-left"
      >
        <Icon className={cn("h-4 w-4", iconClass)} />
        <span className="text-sm font-semibold text-gray-700">{title}</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
          {tasks.length}
        </span>
        <span className="ml-auto text-gray-400">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
      </button>

      {open && (
        <div className="space-y-2">
          {tasks.length === 0 ? (
            <p className="rounded-xl border border-dashed border-gray-200 px-4 py-6 text-center text-sm text-gray-400">
              {emptyText}
            </p>
          ) : (
            tasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onComplete={onComplete}
                onUncomplete={onUncomplete}
                onDelete={onDelete}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default function TasksPage() {
  const {
    overdueTasks,
    todayTasks,
    upcomingTasks,
    completedTasks,
    addTask,
    completeTask,
    uncompleteTask,
    deleteTask,
  } = useTasks();

  const [showCompleted, setShowCompleted] = useState(false);

  // Add task form state
  const [formTitle, setFormTitle] = useState("");
  const [formCompany, setFormCompany] = useState("");
  const [formDue, setFormDue] = useState(new Date().toISOString().slice(0, 10));
  const [formDesc, setFormDesc] = useState("");
  const [formOpen, setFormOpen] = useState(false);

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!formTitle.trim() || !formDue) return;
    addTask({
      title: formTitle.trim(),
      companyName: formCompany.trim() || undefined,
      description: formDesc.trim() || undefined,
      dueDate: formDue,
    });
    setFormTitle("");
    setFormCompany("");
    setFormDesc("");
    setFormDue(new Date().toISOString().slice(0, 10));
    setFormOpen(false);
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Tasks</h2>
          <p className="mt-1 text-sm text-gray-500">
            {overdueTasks.length > 0
              ? `${overdueTasks.length} overdue · `
              : ""}
            {todayTasks.length} due today · {upcomingTasks.length} upcoming
          </p>
        </div>
        <button
          onClick={() => setFormOpen((v) => !v)}
          className="flex items-center gap-2 rounded-lg bg-digitillis-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 transition-opacity"
        >
          <Plus className="h-4 w-4" />
          Add Task
        </button>
      </div>

      {/* Add task form */}
      {formOpen && (
        <form
          onSubmit={handleAdd}
          className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm space-y-3"
        >
          <h3 className="text-sm font-semibold text-gray-800">New Task</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input
              value={formTitle}
              onChange={(e) => setFormTitle(e.target.value)}
              placeholder="Task title *"
              required
              className="col-span-full h-9 rounded-lg border border-gray-200 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
            />
            <input
              value={formCompany}
              onChange={(e) => setFormCompany(e.target.value)}
              placeholder="Company name (optional)"
              className="h-9 rounded-lg border border-gray-200 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
            />
            <input
              type="date"
              value={formDue}
              onChange={(e) => setFormDue(e.target.value)}
              required
              className="h-9 rounded-lg border border-gray-200 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
            />
            <textarea
              value={formDesc}
              onChange={(e) => setFormDesc(e.target.value)}
              placeholder="Description (optional)"
              rows={2}
              className="col-span-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-digitillis-accent/30"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setFormOpen(false)}
              className="rounded-lg border border-gray-200 px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-lg bg-digitillis-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              Add Task
            </button>
          </div>
        </form>
      )}

      {/* Overdue */}
      {overdueTasks.length > 0 && (
        <Section
          title="Overdue"
          icon={AlertCircle}
          iconClass="text-red-500"
          tasks={overdueTasks}
          emptyText="No overdue tasks"
          onComplete={completeTask}
          onUncomplete={uncompleteTask}
          onDelete={deleteTask}
        />
      )}

      {/* Today */}
      <Section
        title="Today"
        icon={Clock}
        iconClass="text-amber-500"
        tasks={todayTasks}
        emptyText="Nothing due today"
        onComplete={completeTask}
        onUncomplete={uncompleteTask}
        onDelete={deleteTask}
      />

      {/* Upcoming */}
      <Section
        title="Upcoming"
        icon={CalendarDays}
        iconClass="text-blue-500"
        tasks={upcomingTasks}
        emptyText="No upcoming tasks"
        onComplete={completeTask}
        onUncomplete={uncompleteTask}
        onDelete={deleteTask}
      />

      {/* Completed toggle */}
      <div>
        <button
          onClick={() => setShowCompleted((v) => !v)}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <ListChecks className="h-4 w-4" />
          {showCompleted ? "Hide" : "Show"} completed ({completedTasks.length})
        </button>
        {showCompleted && (
          <div className="mt-3 space-y-2">
            {completedTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onComplete={completeTask}
                onUncomplete={uncompleteTask}
                onDelete={deleteTask}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
