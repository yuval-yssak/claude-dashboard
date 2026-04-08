import type { Session } from "../types";
import { AnnotationsPanel } from "./AnnotationsPanel";
import { ClaudeTodos } from "./ClaudeTodos";
import { StatusBadge } from "./StatusBadge";

interface SessionCardProps {
	session: Session;
	isOpen: boolean;
	onTogglePanel: () => void;
	onOpenSession: () => void;
	onNotesChange: (value: string) => void;
	onNotesFocus: () => void;
	onNotesBlur: () => void;
	onToggleTodo: (index: number, done: boolean) => void;
	onAddTodo: (text: string) => void;
	onDeleteTodo: (index: number) => void;
	loading: boolean;
}

export function SessionCard({
	session,
	isOpen,
	onTogglePanel,
	onOpenSession,
	onNotesChange,
	onNotesFocus,
	onNotesBlur,
	onToggleTodo,
	onAddTodo,
	onDeleteTodo,
	loading,
}: SessionCardProps) {
	const s = session;
	const openLabel = s.alive ? "Focus" : "Resume";
	const openTitle = s.alive
		? "Bring the host app (Warp/VS Code/Claude) to front"
		: "Resume this session in a new Warp tab";

	const shortCwd = s.cwd
		? s.cwd
				.replace(/^\/Users\/[^/]+/, "~")
				.split("/")
				.slice(-3)
				.join("/")
		: "";

	return (
		<div
			className={`session-card status-${s.status}${!s.alive ? " dead" : ""}`}
		>
			<div className="card-top">
				<div>
					{s.session_name && (
						<div className="session-name">{s.session_name}</div>
					)}
					<div className="project-name">{s.project}</div>
					{s.topic && !s.session_name && <div className="topic">{s.topic}</div>}
					{s.last_user_msg ? (
						<div className="last-msg last-user-msg">{s.last_user_msg}</div>
					) : s.alive ? (
						<div className="last-msg active-hint">Active session</div>
					) : null}
					{s.last_assistant_text && (
						<div
							className="last-msg last-assistant-text"
							title={s.last_assistant_text}
						>
							{s.last_assistant_text}
						</div>
					)}
				</div>
				<div className="card-top-right">
					<button
						type="button"
						className={`open-btn${loading ? " loading" : ""}`}
						title={openTitle}
						onClick={(e) => {
							e.stopPropagation();
							onOpenSession();
						}}
					>
						{loading ? "..." : openLabel}
					</button>
					<StatusBadge status={s.status} />
				</div>
			</div>
			<div className="card-meta">
				<span>{s.last_activity_ago}</span>
				{shortCwd && <span title={s.cwd}>{shortCwd}</span>}
				{s.git_branch && <span>branch: {s.git_branch}</span>}
				<span>{s.file_size_kb} KB</span>
				<span
					className="jsonl-link"
					title={`${s.jsonl_path}\n(click to copy)`}
					onClick={(e) => {
						e.stopPropagation();
						navigator.clipboard.writeText(s.jsonl_path);
					}}
				>
					{s.session_id}
				</span>
			</div>
			<ClaudeTodos todos={s.todos} />
			<AnnotationsPanel
				session={s}
				isOpen={isOpen}
				onToggle={onTogglePanel}
				onNotesChange={onNotesChange}
				onNotesFocus={onNotesFocus}
				onNotesBlur={onNotesBlur}
				onToggleTodo={onToggleTodo}
				onAddTodo={onAddTodo}
				onDeleteTodo={onDeleteTodo}
			/>
		</div>
	);
}
