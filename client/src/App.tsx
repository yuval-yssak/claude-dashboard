import { useCallback, useMemo, useRef, useState } from "react";
import { openSession, saveAnnotation } from "./api";
import { AccountSection } from "./components/AccountSection";
import { Header } from "./components/Header";
import { SummaryBar } from "./components/SummaryBar";
import { Toast } from "./components/Toast";
import { useDebouncedSave } from "./hooks/useDebouncedSave";
import { type ConnectionStatus, useSSE } from "./hooks/useSSE";
import type { DashboardData, Session } from "./types";

function App() {
	const [data, setData] = useState<DashboardData | null>(null);
	const [toastMessage, setToastMessage] = useState<string | null>(null);
	const [loadingSessions, setLoadingSessions] = useState<Set<string>>(
		new Set(),
	);
	const [searchQuery, setSearchQuery] = useState("");
	const [personalFirst, setPersonalFirst] = useState(
		() => localStorage.getItem("dashboard-personal-first") === "true",
	);
	// Force re-render counter for panel toggles
	const [, setRenderTick] = useState(0);
	const [connectionStatus, setConnectionStatus] =
		useState<ConnectionStatus>("connecting");

	const openPanelsRef = useRef(new Set<string>());
	const activeEditsRef = useRef(new Set<string>());
	const localNotesRef = useRef(new Map<string, string>());
	const toastTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

	const debounce = useDebouncedSave();

	const showToast = useCallback((msg: string) => {
		setToastMessage(msg);
		if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
		toastTimerRef.current = setTimeout(() => setToastMessage(null), 3000);
	}, []);

	const findSession = useCallback(
		(sessionId: string, d: DashboardData): Session | null => {
			for (const a of d.accounts) {
				for (const s of a.sessions) {
					if (s.session_id === sessionId) return s;
				}
			}
			return null;
		},
		[],
	);

	const handleSSEData = useCallback((newData: DashboardData) => {
		// Preserve local notes for sessions being actively edited
		for (const account of newData.accounts) {
			for (const session of account.sessions) {
				if (activeEditsRef.current.has(session.session_id)) {
					const localVal = localNotesRef.current.get(session.session_id);
					if (localVal !== undefined) {
						session.user_notes = localVal;
					}
				}
			}
		}
		setData(newData);
	}, []);

	const sseStatus = useSSE<DashboardData>("sessions", handleSSEData);

	// Sync SSE status to state for Header
	if (sseStatus !== connectionStatus) {
		setConnectionStatus(sseStatus);
	}

	const handleTogglePanel = useCallback((sessionId: string) => {
		const panels = openPanelsRef.current;
		if (panels.has(sessionId)) {
			panels.delete(sessionId);
		} else {
			panels.add(sessionId);
		}
		setRenderTick((t) => t + 1);
	}, []);

	const handleOpenSession = useCallback(
		async (sessionId: string) => {
			setLoadingSessions((prev) => new Set(prev).add(sessionId));
			try {
				const result = await openSession(sessionId);
				showToast(result.detail || (result.ok ? "Done" : "Failed"));
			} catch (e: unknown) {
				showToast(`Error: ${e instanceof Error ? e.message : String(e)}`);
			} finally {
				setLoadingSessions((prev) => {
					const next = new Set(prev);
					next.delete(sessionId);
					return next;
				});
			}
		},
		[showToast],
	);

	const handleNotesChange = useCallback(
		(sessionId: string, value: string) => {
			localNotesRef.current.set(sessionId, value);
			// Update data in-place for immediate UI feedback
			setData((prev) => {
				if (!prev) return prev;
				const s = findSession(sessionId, prev);
				if (s) s.user_notes = value;
				return { ...prev };
			});
			debounce(`notes-${sessionId}`, () => {
				const currentData = localNotesRef.current.get(sessionId) ?? value;
				// Get current todos from data
				setData((prev) => {
					if (!prev) return prev;
					const s = findSession(sessionId, prev);
					saveAnnotation(sessionId, currentData, s?.user_todos || []);
					return prev;
				});
			});
		},
		[debounce, findSession],
	);

	const handleNotesFocus = useCallback((sessionId: string) => {
		activeEditsRef.current.add(sessionId);
	}, []);

	const handleNotesBlur = useCallback((sessionId: string) => {
		activeEditsRef.current.delete(sessionId);
	}, []);

	const handleToggleTodo = useCallback(
		(sessionId: string, index: number, done: boolean) => {
			setData((prev) => {
				if (!prev) return prev;
				const s = findSession(sessionId, prev);
				if (!s?.user_todos[index]) return prev;
				s.user_todos[index].done = done;
				saveAnnotation(sessionId, s.user_notes || "", s.user_todos);
				return { ...prev };
			});
		},
		[findSession],
	);

	const handleAddTodo = useCallback(
		(sessionId: string, text: string) => {
			setData((prev) => {
				if (!prev) return prev;
				const s = findSession(sessionId, prev);
				if (!s) return prev;
				if (!s.user_todos) s.user_todos = [];
				s.user_todos.push({ text, done: false });
				saveAnnotation(sessionId, s.user_notes || "", s.user_todos);
				return { ...prev };
			});
		},
		[findSession],
	);

	const handleDeleteTodo = useCallback(
		(sessionId: string, index: number) => {
			setData((prev) => {
				if (!prev) return prev;
				const s = findSession(sessionId, prev);
				if (!s?.user_todos) return prev;
				s.user_todos.splice(index, 1);
				saveAnnotation(sessionId, s.user_notes || "", s.user_todos);
				return { ...prev };
			});
		},
		[findSession],
	);

	const totalSessions = data
		? data.accounts.reduce((sum, a) => sum + a.sessions.length, 0)
		: 0;

	const handleToggleWorkspace = useCallback(() => {
		setPersonalFirst((prev) => {
			const next = !prev;
			localStorage.setItem("dashboard-personal-first", String(next));
			return next;
		});
	}, []);

	const filteredAccounts = useMemo(() => {
		if (!data) return [];
		const q = searchQuery.trim().toLowerCase();
		let accounts = q
			? data.accounts.map((a) => ({
					...a,
					sessions: a.sessions.filter(
						(s) =>
							(s.session_name || "").toLowerCase().includes(q) ||
							s.project.toLowerCase().includes(q) ||
							(s.git_branch || "").toLowerCase().includes(q) ||
							s.status.toLowerCase().includes(q) ||
							(s.last_user_msg || "").toLowerCase().includes(q),
					),
				}))
			: data.accounts;
		if (personalFirst) {
			accounts = [...accounts].reverse();
		}
		return accounts;
	}, [data, searchQuery, personalFirst]);

	return (
		<>
			<Header
				generatedAt={data?.generated_at ?? null}
				connectionStatus={connectionStatus}
			/>
			{data && <SummaryBar accounts={data.accounts} />}
			{data && totalSessions > 0 && (
				<div className="filter-row">
					<input
						className="search-input"
						type="text"
						placeholder="Filter by name, project, branch, status..."
						value={searchQuery}
						onChange={(e) => setSearchQuery(e.target.value)}
					/>
					<button
						type="button"
						className={`workspace-toggle ${personalFirst ? "personal" : "work"}`}
						onClick={handleToggleWorkspace}
						title={personalFirst ? "Personal on top" : "Work on top"}
					>
						<span className="workspace-toggle-label">
							{personalFirst ? "Personal" : "Work"}
						</span>
						<span className="workspace-toggle-icon">&#x21C5;</span>
					</button>
				</div>
			)}
			{!data && <div className="empty-state">Loading sessions...</div>}
			{data && totalSessions === 0 && (
				<div className="empty-state">No recent sessions found.</div>
			)}
			{data &&
				filteredAccounts.map((a) => (
					<AccountSection
						key={a.config_dir}
						account={a}
						openPanels={openPanelsRef.current}
						loadingSessions={loadingSessions}
						onTogglePanel={handleTogglePanel}
						onOpenSession={handleOpenSession}
						onNotesChange={handleNotesChange}
						onNotesFocus={handleNotesFocus}
						onNotesBlur={handleNotesBlur}
						onToggleTodo={handleToggleTodo}
						onAddTodo={handleAddTodo}
						onDeleteTodo={handleDeleteTodo}
					/>
				))}
			<Toast message={toastMessage} />
		</>
	);
}

export default App;
