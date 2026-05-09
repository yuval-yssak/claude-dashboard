export type SessionStatus =
	| "thinking"
	| "subagent"
	| "hook"
	| "questioning"
	| "approving"
	| "waiting"
	| "recent"
	| "idle"
	| "unknown";

export interface ClaudeTodo {
	content: string;
	status: "completed" | "in_progress" | "pending";
	activeForm?: string;
}

export interface UserTodo {
	text: string;
	done: boolean;
}

export type PermissionModeConfidence =
	| "observed"
	| "inferred-exit-plan"
	| "inferred-edits-after-plan"
	| "inferred-plan-at-tail"
	| "none";

export interface PermissionModeInfo {
	observed: string | null;
	inferred: string | null;
	confidence: PermissionModeConfidence;
	evidence: {
		last_permission_mode_entry: string | null;
		lines_since_entry: number;
		exit_plan_mode_seen_after: boolean;
		edit_tools_seen_after: boolean;
		enter_plan_mode_seen_after: boolean;
	};
}

export type PlanPendingConfidence =
	| "observed"
	| "inferred-stale-plan-entry"
	| "not-pending";

export interface PlanPendingInfo {
	pending: boolean;
	confidence: PlanPendingConfidence;
	evidence: {
		last_permission_mode_entry: string | null;
		assistant_activity_after: boolean;
		exit_plan_mode_seen: boolean;
		enter_plan_mode_after_exit: boolean;
	};
}

export type HostId =
	| "warp"
	| "iterm2"
	| "terminal"
	| "claude-desktop"
	| "vscode-terminal"
	| "vscode-extension"
	| "jetbrains-terminal"
	| "jetbrains-extension";

export interface SessionHost {
	id: HostId;
	label: string;
	app: string;
}

export interface Session {
	session_id: string;
	session_name: string;
	project: string;
	cwd: string;
	status: SessionStatus;
	pid: number | null;
	alive: boolean;
	host: SessionHost | null;
	config_dir: string;
	last_activity: string | null;
	last_activity_ago: string;
	topic: string | null;
	last_user_msg: string | null;
	last_assistant_text: string | null;
	current_activity: string | null;
	user_msg_stale: boolean;
	git_branch: string | null;
	model: string | null;
	thinking_recent: boolean;
	permission_mode: string | null;
	permission_mode_info: PermissionModeInfo;
	plan_pending_info: PlanPendingInfo;
	kind: string;
	todos: ClaudeTodo[] | null;
	file_size_kb: number;
	jsonl_path: string;
	plan_file_path: string | null;
	plan_file_exists: boolean;
	user_notes: string;
	user_todos: UserTodo[];
}

export interface RateLimitEntry {
	used_percentage: number;
	resets_at: number;
	is_stale: boolean;
}

export interface RateLimits {
	five_hour?: RateLimitEntry;
	seven_day?: RateLimitEntry;
	updated_at: number;
}

export interface Account {
	email: string;
	config_dir: string;
	sessions: Session[];
	rate_limits: RateLimits | null;
}

export interface CardPosition {
	index: number;
	pinned: boolean;
}

export interface LayoutPreferences {
	positions: Record<string, Record<string, CardPosition>>;
}

export interface DashboardData {
	accounts: Account[];
	generated_at: string;
}
