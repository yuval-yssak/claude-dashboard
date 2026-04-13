import type { RateLimitEntry, RateLimits } from "../types";

interface UsageBarsProps {
	rateLimits: RateLimits | null;
}

function fillColor(pct: number): string {
	if (pct >= 95) return "#e74c3c";
	if (pct >= 80) return "#e67e22";
	if (pct >= 50) return "#f1c40f";
	return "#2ecc71";
}

function formatResetTime(epochSecs: number): string {
	const date = new Date(epochSecs * 1000);
	const now = new Date();
	// Same day: show time only; otherwise show date
	if (date.toDateString() === now.toDateString()) {
		return `Resets at ${date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
	}
	return `Resets ${date.toLocaleDateString([], { month: "short", day: "numeric" })} at ${date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function UsageBar({ label, entry }: { label: string; entry: RateLimitEntry }) {
	const pct = Math.min(100, Math.max(0, entry.used_percentage));
	const staleClass = entry.is_stale ? " usage-bar-stale" : "";

	return (
		<div
			className={`usage-bar-group${staleClass}`}
			title={formatResetTime(entry.resets_at)}
		>
			<span className="usage-bar-label">
				{label}: {Math.round(pct)}%{entry.is_stale ? " (stale)" : ""}
			</span>
			<div className="usage-bar-track">
				<div
					className="usage-bar-fill"
					style={{
						width: `${pct}%`,
						backgroundColor: fillColor(pct),
					}}
				/>
			</div>
		</div>
	);
}

export function UsageBars({ rateLimits }: UsageBarsProps) {
	if (!rateLimits) return null;

	const { five_hour, seven_day } = rateLimits;
	if (!five_hour && !seven_day) return null;

	return (
		<div className="usage-bars">
			{five_hour && <UsageBar label="5h" entry={five_hour} />}
			{seven_day && <UsageBar label="7d" entry={seven_day} />}
		</div>
	);
}
