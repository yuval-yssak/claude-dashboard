export type SessionStatus =
	| "thinking"
	| "subagent"
	| "hook"
	| "questioning"
	| "approving"
	| "waiting"
	| "recent"
	| "idle";

export interface ClaudeTodo {
	content: string;
	status: "completed" | "in_progress" | "pending";
	activeForm?: string;
}

export interface UserTodo {
	text: string;
	done: boolean;
}

export interface Session {
	session_id: string;
	session_name: string;
	project: string;
	cwd: string;
	status: SessionStatus;
	pid: number | null;
	alive: boolean;
	config_dir: string;
	last_activity: string | null;
	last_activity_ago: string;
	topic: string | null;
	last_user_msg: string | null;
	last_assistant_text: string | null;
	current_activity: string | null;
	user_msg_stale: boolean;
	git_branch: string | null;
	permission_mode: string | null;
	kind: string;
	todos: ClaudeTodo[] | null;
	file_size_kb: number;
	jsonl_path: string;
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
