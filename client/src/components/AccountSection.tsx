import type { Account } from "../types";
import { SessionCard } from "./SessionCard";

interface AccountSectionProps {
	account: Account;
	openPanels: Set<string>;
	loadingSessions: Set<string>;
	onTogglePanel: (sessionId: string) => void;
	onOpenSession: (sessionId: string) => void;
	onNotesChange: (sessionId: string, value: string) => void;
	onNotesFocus: (sessionId: string) => void;
	onNotesBlur: (sessionId: string) => void;
	onToggleTodo: (sessionId: string, index: number, done: boolean) => void;
	onAddTodo: (sessionId: string, text: string) => void;
	onDeleteTodo: (sessionId: string, index: number) => void;
}

export function AccountSection({
	account,
	openPanels,
	loadingSessions,
	onTogglePanel,
	onOpenSession,
	onNotesChange,
	onNotesFocus,
	onNotesBlur,
	onToggleTodo,
	onAddTodo,
	onDeleteTodo,
}: AccountSectionProps) {
	if (account.sessions.length === 0) return null;

	const active = account.sessions.filter(
		(s) =>
			s.status === "thinking" || s.status === "subagent" || s.status === "hook",
	).length;

	return (
		<div className="account">
			<div className="account-header">
				<span className="account-email">{account.email}</span>
				<span className="account-count">
					{account.sessions.length} sessions
					{active ? ` \u00B7 ${active} active` : ""}
				</span>
			</div>
			<div className="session-grid">
				{account.sessions.map((s) => (
					<SessionCard
						key={s.session_id}
						session={s}
						isOpen={openPanels.has(s.session_id)}
						loading={loadingSessions.has(s.session_id)}
						onTogglePanel={() => onTogglePanel(s.session_id)}
						onOpenSession={() => onOpenSession(s.session_id)}
						onNotesChange={(v) => onNotesChange(s.session_id, v)}
						onNotesFocus={() => onNotesFocus(s.session_id)}
						onNotesBlur={() => onNotesBlur(s.session_id)}
						onToggleTodo={(i, d) => onToggleTodo(s.session_id, i, d)}
						onAddTodo={(t) => onAddTodo(s.session_id, t)}
						onDeleteTodo={(i) => onDeleteTodo(s.session_id, i)}
					/>
				))}
			</div>
		</div>
	);
}
