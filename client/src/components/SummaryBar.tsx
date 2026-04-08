import type { Account, SessionStatus } from "../types";

interface SummaryBarProps {
	accounts: Account[];
}

const STATUS_ITEMS: { key: SessionStatus; label: string; color: string }[] = [
	{ key: "thinking", label: "thinking", color: "var(--thinking)" },
	{ key: "subagent", label: "subagent", color: "var(--subagent)" },
	{ key: "hook", label: "hook", color: "var(--hook)" },
	{ key: "approving", label: "approving", color: "var(--approving)" },
	{ key: "waiting", label: "waiting", color: "var(--waiting)" },
	{ key: "recent", label: "recent", color: "var(--recent)" },
	{ key: "idle", label: "idle", color: "var(--idle)" },
];

export function SummaryBar({ accounts }: SummaryBarProps) {
	const counts: Record<string, number> = {
		thinking: 0,
		subagent: 0,
		hook: 0,
		approving: 0,
		waiting: 0,
		recent: 0,
		idle: 0,
	};
	let total = 0;

	for (const a of accounts) {
		for (const s of a.sessions) {
			total++;
			if (s.status in counts) counts[s.status]++;
		}
	}

	return (
		<div className="summary-bar">
			<div className="summary-item">
				<span className="summary-count">{total}</span> active sessions
			</div>
			{STATUS_ITEMS.filter(({ key }) => counts[key] > 0).map(
				({ key, label, color }) => (
					<div className="summary-item" key={key}>
						<div className="summary-dot" style={{ background: color }} />
						<span className="summary-count">{counts[key]}</span> {label}
					</div>
				),
			)}
		</div>
	);
}
