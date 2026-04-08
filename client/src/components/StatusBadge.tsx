import type { SessionStatus } from "../types";

interface StatusBadgeProps {
	status: SessionStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
	return <span className={`status-badge ${status}`}>{status}</span>;
}
