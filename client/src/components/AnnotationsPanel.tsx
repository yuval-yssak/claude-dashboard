import { type KeyboardEvent, useEffect, useRef } from "react";
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
	const notesTextareaRef = useRef<HTMLTextAreaElement>(null);
	const wasOpenRef = useRef(isOpen);

	// When the panel transitions from closed → open, focus the notes textarea
	// so the user can start typing immediately. Triggered by both keyboard
	// hint activation and click; either way, focus is what they want next.
	useEffect(() => {
		if (!wasOpenRef.current && isOpen) {
			notesTextareaRef.current?.focus();
		}
		wasOpenRef.current = isOpen;
	}, [isOpen]);

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

	// Hint proxies expand the panel (if needed) and focus the right input.
	// They're always in the DOM so the per-task letters K/L/M land predictably,
	// regardless of whether the panel is currently expanded.
	const focusNotesViaHint = () => {
		if (!isOpen) onToggle();
		// Defer to next tick so the body has finished its display flip.
		setTimeout(() => notesTextareaRef.current?.focus(), 0);
	};
	const focusAddTaskViaHint = () => {
		if (!isOpen) onToggle();
		setTimeout(() => addInputRef.current?.focus(), 0);
	};

	return (
		<div className="annotations-section">
			{/* Notes preview - shown when closed AND has notes */}
			{!isOpen && hasNotes && (
				<button
					type="button"
					className="notes-preview"
					onClick={onToggle}
					title="Click to edit"
				>
					{session.user_notes}
				</button>
			)}

			{/* Edit toggle — kept BEFORE the tasks/notes hint targets in document
			    order so its letter (H) stays stable as task count varies. */}
			<button
				type="button"
				className="annotations-edit-toggle"
				data-hint-target=""
				data-hint-scope="card"
				data-hint-card-id={session.session_id}
				data-hint-label={
					hasNotes || hasTodos ? "Edit notes & tasks" : "Add notes & tasks"
				}
				onClick={onToggle}
			>
				<span className={`arrow${isOpen ? " open" : ""}`}>&#9654;</span>
				{hasNotes || hasTodos ? "Edit notes & tasks" : "+ Add notes & tasks"}
			</button>

			{/* Expandable: textarea + add task row. Hint proxies live next to
			    each input so their pills line up vertically with the field they
			    represent. When the panel is collapsed the body is display:none,
			    so the proxies — and the hint slots they reserve — disappear too;
			    in that state, per-task letters slide up to fill those slots. */}
			<div className={`annotations-body${isOpen ? " open" : ""}`}>
				<div className="ann-label">Notes</div>
				<div className="notes-row">
					<button
						type="button"
						className="hint-proxy hint-proxy-notes"
						data-hint-target=""
						data-hint-scope="card"
						data-hint-card-id={session.session_id}
						data-hint-label="Edit notes"
						aria-hidden="true"
						tabIndex={-1}
						onClick={focusNotesViaHint}
					/>
					<textarea
						ref={notesTextareaRef}
						className="notes-area"
						placeholder="Jot down what you're struggling with, what's left..."
						value={session.user_notes || ""}
						onFocus={onNotesFocus}
						onBlur={onNotesBlur}
						onChange={(e) => onNotesChange(e.target.value)}
					/>
				</div>
				<div className="add-todo-row">
					<button
						type="button"
						className="hint-proxy hint-proxy-add-task"
						data-hint-target=""
						data-hint-scope="card"
						data-hint-card-id={session.session_id}
						data-hint-label="Add a task"
						aria-hidden="true"
						tabIndex={-1}
						onClick={focusAddTaskViaHint}
					/>
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

			{/* User tasks - ALWAYS visible and interactive. Rendered LAST so the
			    per-task hint letters fall after all stable card targets. */}
			{hasTodos && (
				<div className="user-todos-inline">
					<div className="ann-label-inline">
						Tasks — {todosDone}/{todosTotal}
					</div>
					{session.user_todos.map((t: UserTodo, i: number) => (
						<div className="user-todo-item" key={i}>
							<input
								type="checkbox"
								className="user-todo-cb"
								checked={t.done}
								data-hint-target=""
								data-hint-scope="card"
								data-hint-card-id={session.session_id}
								data-hint-label={`Toggle task: ${t.text}`}
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
				</div>
			)}
		</div>
	);
}
