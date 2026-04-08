import type { ClaudeTodo } from "../types";

const STATUS_ICONS: Record<string, string> = {
	completed: "\u2713",
	in_progress: "\u25B6",
	pending: "\u2022",
};

interface ClaudeTodosProps {
	todos: ClaudeTodo[] | null;
}

export function ClaudeTodos({ todos }: ClaudeTodosProps) {
	if (!todos || todos.length === 0) return null;

	const total = todos.length;
	const done = todos.filter((t) => t.status === "completed").length;
	const inProg = todos.filter((t) => t.status === "in_progress").length;
	const donePct = (done / total) * 100;
	const ipPct = (inProg / total) * 100;
	const fillWidth = donePct + ipPct;
	const gradientSplit =
		donePct + ipPct > 0 ? (donePct / (donePct + ipPct)) * 100 : 0;

	return (
		<div className="todo-section">
			<div className="todo-header">
				Claude Tasks &mdash; {done}/{total} done
			</div>
			{todos.map((t, i) => (
				<div className="todo-item" key={i}>
					<div className={`todo-icon ${t.status}`}>
						{STATUS_ICONS[t.status] || "\u2022"}
					</div>
					<div className={`todo-text ${t.status}`}>
						{t.status === "in_progress" ? t.activeForm : t.content}
					</div>
				</div>
			))}
			<div className="progress-bar">
				<div
					className="progress-fill"
					style={{
						width: `${fillWidth}%`,
						background: `linear-gradient(90deg, var(--done) ${gradientSplit}%, var(--in-progress) 100%)`,
					}}
				/>
			</div>
		</div>
	);
}
