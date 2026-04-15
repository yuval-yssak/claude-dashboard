import { resolveStatusDisplay } from "../statusDisplay";
import type { PlanPendingInfo, SessionStatus } from "../types";
import { UncertaintyAnchor } from "./UncertaintyTooltip";

interface StatusBadgeProps {
	status: SessionStatus;
	planPendingInfo: PlanPendingInfo;
	strict: boolean;
}

export function StatusBadge({
	status,
	planPendingInfo,
	strict,
}: StatusBadgeProps) {
	const display = resolveStatusDisplay(status, planPendingInfo, strict);
	return (
		<UncertaintyAnchor
			content={display.uncertainty}
			className={`status-badge ${display.className}`}
		>
			{display.label}
		</UncertaintyAnchor>
	);
}
