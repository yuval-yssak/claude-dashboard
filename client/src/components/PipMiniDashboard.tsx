import { useEffect, useMemo, useRef, useState } from "react";
import type { Account, Session, SessionStatus } from "../types";

export type PipMode = "count" | "thinking" | "active";

interface PipMiniDashboardProps {
	accounts: Account[];
	mode: PipMode;
	onCycleMode: () => void;
	onFocusSession: (sessionId: string) => void;
}

const ACTIVE_STATUSES: ReadonlySet<SessionStatus> = new Set([
	"thinking",
	"subagent",
	"hook",
	"questioning",
	"approving",
	"waiting",
]);

const MODE_LABELS: Record<PipMode, string> = {
	count: "count",
	thinking: "thinking",
	active: "active",
};

const flattenSessions = (accounts: Account[]): Session[] =>
	accounts.flatMap((a) => a.sessions);

const isThinking = (s: Session): boolean => s.status === "thinking";

const isActive = (s: Session): boolean => ACTIVE_STATUSES.has(s.status);

const useClearedFlash = (thinkingIds: string[]) => {
	const [flashedIds, setFlashedIds] = useState<Set<string>>(new Set());
	const [recentlyCleared, setRecentlyCleared] = useState(false);
	const previousIdsRef = useRef<Set<string>>(new Set(thinkingIds));
	const clearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	useEffect(() => {
		const previous = previousIdsRef.current;
		const current = new Set(thinkingIds);
		const cleared = [...previous].filter((id) => !current.has(id));
		previousIdsRef.current = current;
		if (cleared.length === 0) return;
		setFlashedIds((prev) => {
			const next = new Set(prev);
			for (const id of cleared) next.add(id);
			return next;
		});
		setRecentlyCleared(true);
		if (clearTimerRef.current) clearTimeout(clearTimerRef.current);
		clearTimerRef.current = setTimeout(() => {
			setFlashedIds(new Set());
			setRecentlyCleared(false);
		}, 1500);
	}, [thinkingIds]);

	return { flashedIds, recentlyCleared };
};

interface SessionRowProps {
	session: Session;
	flashing: boolean;
	onFocus: () => void;
}

function SessionRow({ session, flashing, onFocus }: SessionRowProps) {
	const title = session.session_name || session.topic || session.project;
	const rowClass = `pip-row pip-status-${session.status}${flashing ? " pip-flash" : ""}`;
	return (
		<button type="button" className={rowClass} onClick={onFocus} title={title}>
			<span className={`pip-dot pip-dot-${session.status}`} />
			<span className="pip-row-title">{title}</span>
			<span className="pip-row-status">{session.status}</span>
		</button>
	);
}

interface CountViewProps {
	count: number;
	recentlyCleared: boolean;
}

function CountView({ count, recentlyCleared }: CountViewProps) {
	if (count === 0) {
		return (
			<div
				className={`pip-count pip-count-clear${recentlyCleared ? " pip-flash" : ""}`}
			>
				<span className="pip-count-icon">✓</span>
				<span className="pip-count-label">all clear</span>
			</div>
		);
	}
	return (
		<div className="pip-count">
			<span className="pip-count-number">{count}</span>
			<span className="pip-count-label">thinking</span>
		</div>
	);
}

interface ListViewProps {
	sessions: Session[];
	flashedIds: Set<string>;
	emptyLabel: string;
	onFocusSession: (sessionId: string) => void;
}

function ListView({
	sessions,
	flashedIds,
	emptyLabel,
	onFocusSession,
}: ListViewProps) {
	if (sessions.length === 0) {
		return <div className="pip-empty">{emptyLabel}</div>;
	}
	return (
		<div className="pip-list">
			{sessions.map((s) => (
				<SessionRow
					key={s.session_id}
					session={s}
					flashing={flashedIds.has(s.session_id)}
					onFocus={() => onFocusSession(s.session_id)}
				/>
			))}
		</div>
	);
}

export function PipMiniDashboard({
	accounts,
	mode,
	onCycleMode,
	onFocusSession,
}: PipMiniDashboardProps) {
	const allSessions = useMemo(() => flattenSessions(accounts), [accounts]);
	const thinkingSessions = useMemo(
		() => allSessions.filter(isThinking),
		[allSessions],
	);
	const activeSessions = useMemo(
		() => allSessions.filter(isActive),
		[allSessions],
	);
	const thinkingIds = useMemo(
		() => thinkingSessions.map((s) => s.session_id),
		[thinkingSessions],
	);
	const { flashedIds, recentlyCleared } = useClearedFlash(thinkingIds);

	return (
		<div className="pip-app">
			<div className="pip-header">
				<button
					type="button"
					className="pip-cycle"
					onClick={onCycleMode}
					title="Cycle view: count → thinking → active"
				>
					{MODE_LABELS[mode]}
				</button>
			</div>
			<div className="pip-body">
				{mode === "count" && (
					<CountView
						count={thinkingSessions.length}
						recentlyCleared={recentlyCleared}
					/>
				)}
				{mode === "thinking" && (
					<ListView
						sessions={thinkingSessions}
						flashedIds={flashedIds}
						emptyLabel="no thinking sessions"
						onFocusSession={onFocusSession}
					/>
				)}
				{mode === "active" && (
					<ListView
						sessions={activeSessions}
						flashedIds={flashedIds}
						emptyLabel="no active sessions"
						onFocusSession={onFocusSession}
					/>
				)}
			</div>
		</div>
	);
}
