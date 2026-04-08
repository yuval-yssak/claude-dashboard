export type SessionStatus =
	| "thinking"
	| "subagent"
	| "hook"
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
	git_branch: string | null;
	kind: string;
	todos: ClaudeTodo[] | null;
	file_size_kb: number;
	user_notes: string;
	user_todos: UserTodo[];
}

export interface Account {
	email: string;
	config_dir: string;
	sessions: Session[];
}

export interface DashboardData {
	accounts: Account[];
	generated_at: string;
}
