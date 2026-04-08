import { type KeyboardEvent, useRef } from "react";
import type { Session, UserTodo } from "../types";

interface AnnotationsPanelProps {
	session: Session;
	isOpen: boolean;
	onToggle: () => void;
	onNotesChange: (value: string) => void;
	onNotesFocus: () => void;
	onNotesBlur: () => void;
	onToggleTodo: (index: number, done: boolean) => void;
	onAddTodo: (text: string) => void;
	onDeleteTodo: (index: number) => void;
}

export function AnnotationsPanel({
	session,
	isOpen,
	onToggle,
	onNotesChange,
	onNotesFocus,
	onNotesBlur,
	onToggleTodo,
	onAddTodo,
	onDeleteTodo,
}: AnnotationsPanelProps) {
	const addInputRef = useRef<HTMLInputElement>(null);

	const hasNotes = session.user_notes && session.user_notes.trim().length > 0;
	const hasTodos = session.user_todos && session.user_todos.length > 0;
	const todosDone = hasTodos
		? session.user_todos.filter((t: UserTodo) => t.done).length
		: 0;
	const todosTotal = hasTodos ? session.user_todos.length : 0;

	const handleAdd = () => {
		const input = addInputRef.current;
		if (!input?.value.trim()) return;
		onAddTodo(input.value.trim());
		input.value = "";
	};

	const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
		if (e.key === "Enter") handleAdd();
	};

	return (
		<div className="annotations-section">
			<div className="annotations-toggle" onClick={onToggle}>
				<span className={`arrow${isOpen ? " open" : ""}`}>&#9654;</span> My
				Notes & Tasks
				{!isOpen && hasNotes && (
					<span className="notes-indicator">has notes</span>
				)}
				{!isOpen && hasTodos && (
					<span className="todos-indicator">
						{todosDone}/{todosTotal} tasks
					</span>
				)}
			</div>
			<div className={`annotations-body${isOpen ? " open" : ""}`}>
				<div className="ann-label">Notes</div>
				<textarea
					className="notes-area"
					placeholder="Jot down what you're struggling with, what's left..."
					value={session.user_notes || ""}
					onFocus={onNotesFocus}
					onBlur={onNotesBlur}
					onChange={(e) => onNotesChange(e.target.value)}
				/>
				<div className="user-todos-list">
					<div className="ann-label">Your checklist</div>
					{(session.user_todos || []).map((t: UserTodo, i: number) => (
						<div className="user-todo-item" key={i}>
							<input
								type="checkbox"
								className="user-todo-cb"
								checked={t.done}
								onChange={(e) => onToggleTodo(i, e.target.checked)}
							/>
							<span className={`user-todo-text${t.done ? " done" : ""}`}>
								{t.text}
							</span>
							<button
								type="button"
								className="user-todo-delete"
								onClick={() => onDeleteTodo(i)}
							>
								&times;
							</button>
						</div>
					))}
					<div className="add-todo-row">
						<input
							type="text"
							className="add-todo-input"
							ref={addInputRef}
							placeholder="Add a task..."
							onKeyDown={handleKeyDown}
						/>
						<button type="button" className="add-todo-btn" onClick={handleAdd}>
							Add
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}
