import { forwardRef } from "react";
import type { Session } from "../types";
import { AnnotationsPanel } from "./AnnotationsPanel";
import { ClaudeTodos } from "./ClaudeTodos";
import { CopyPathBadge } from "./CopyPathBadge";
import { ModeBadge } from "./ModeBadge";
import { PlanViewer } from "./PlanViewer";
import { StatusBadge } from "./StatusBadge";

interface SessionCardProps {
	session: Session;
	strictUnknown: boolean;
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
	isPinned?: boolean;
	isPendingMove?: boolean;
	onTogglePin?: () => void;
	onMoveCard?: (direction: "up" | "down" | "left" | "right") => void;
	onCopyPath: (message: string) => void;
	dragHandleProps?: Record<string, unknown>;
}

export const SessionCard = forwardRef<HTMLDivElement, SessionCardProps>(
	function SessionCard(
		{
			session,
			strictUnknown,
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
			isPinned,
			isPendingMove,
			onTogglePin,
			onMoveCard,
			onCopyPath,
			dragHandleProps,
		},
		ref,
	) {
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

		const classes = [
			"session-card",
			`status-${s.status}`,
			!s.alive && "dead",
			isPinned && "pinned",
			isPendingMove && "pending-move",
		]
			.filter(Boolean)
			.join(" ");

		const handleKeyDown = (e: React.KeyboardEvent) => {
			if (!onMoveCard || !e.ctrlKey) return;
			const dirMap: Record<string, "up" | "down" | "left" | "right"> = {
				ArrowUp: "up",
				ArrowDown: "down",
				ArrowLeft: "left",
				ArrowRight: "right",
			};
			const dir = dirMap[e.key];
			if (dir) {
				e.preventDefault();
				onMoveCard(dir);
			}
		};

		return (
			<div ref={ref} className={classes} onKeyDown={handleKeyDown} tabIndex={0}>
				<div className="card-top">
					<div className="card-top-title">
						{s.session_name && (
							<div className="session-name">{s.session_name}</div>
						)}
						<div className="project-name">{s.project}</div>
					</div>
					<div className="card-top-right">
						<button
							type="button"
							className="drag-handle"
							title="Drag to reorder"
							{...(dragHandleProps || {})}
						>
							<svg
								width="12"
								height="18"
								viewBox="0 0 12 18"
								fill="currentColor"
							>
								<circle cx="3" cy="3" r="1.5" />
								<circle cx="9" cy="3" r="1.5" />
								<circle cx="3" cy="9" r="1.5" />
								<circle cx="9" cy="9" r="1.5" />
								<circle cx="3" cy="15" r="1.5" />
								<circle cx="9" cy="15" r="1.5" />
							</svg>
						</button>
						{onTogglePin && (
							<button
								type="button"
								className={`pin-btn${isPinned ? " pinned" : ""}`}
								title={isPinned ? "Unpin from top" : "Pin to top"}
								onClick={(e) => {
									e.stopPropagation();
									onTogglePin();
								}}
							>
								<svg
									width="14"
									height="14"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
									strokeLinejoin="round"
								>
									<line x1="12" y1="17" x2="12" y2="22" />
									<path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z" />
								</svg>
							</button>
						)}
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
						<StatusBadge
							status={s.status}
							planPendingInfo={s.plan_pending_info}
							strict={strictUnknown}
						/>
					</div>
				</div>
				{s.topic && !s.session_name && <div className="topic">{s.topic}</div>}
				{s.last_user_msg ? (
					<div
						className={`last-msg last-user-msg${s.user_msg_stale ? " stale" : ""}`}
					>
						{s.last_user_msg}
					</div>
				) : s.alive ? (
					<div className="last-msg active-hint">Active session</div>
				) : null}
				{s.current_activity && s.alive ? (
					<div className="last-msg current-activity">{s.current_activity}</div>
				) : s.last_assistant_text ? (
					<div
						className="last-msg last-assistant-text"
						title={s.last_assistant_text}
					>
						{s.last_assistant_text}
					</div>
				) : null}
				<div className="card-meta">
					<span>{s.last_activity_ago}</span>
					{shortCwd && <span title={s.cwd}>{shortCwd}</span>}
					{s.git_branch && <span>branch: {s.git_branch}</span>}
					<ModeBadge info={s.permission_mode_info} strict={strictUnknown} />
					<span>{s.file_size_kb} KB</span>
					<CopyPathBadge
						sessionId={s.session_id}
						jsonlPath={s.jsonl_path}
						onCopied={onCopyPath}
					/>
				</div>
				<ClaudeTodos todos={s.todos} />
				<PlanViewer
					sessionId={s.session_id}
					planPath={s.plan_file_path}
					planExists={s.plan_file_exists}
				/>
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
	},
);
