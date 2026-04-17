import type { UncertaintyContent } from "./components/UncertaintyTooltip";
import type { PlanPendingInfo, SessionStatus } from "./types";

export interface StatusDisplay {
	className: string;
	label: string;
	uncertainty: UncertaintyContent | null;
}

const buildUnknownPlanContent = (info: PlanPendingInfo): UncertaintyContent => {
	const e = info.evidence;
	const rows: Array<{ label: string; value: string }> = [];
	if (e.last_permission_mode_entry) {
		rows.push({
			label: "JSONL entry",
			value: `permission-mode:${e.last_permission_mode_entry}`,
		});
	}
	rows.push({
		label: "Activity after",
		value: e.assistant_activity_after ? "yes" : "no",
	});
	rows.push({
		label: "ExitPlanMode",
		value: e.exit_plan_mode_seen ? "yes" : "no",
	});
	return {
		title: "Possibly plan-pending",
		evidenceRows: rows,
		explanation:
			"A permission-mode:plan entry exists in the JSONL and assistant activity followed it with no explicit ExitPlanMode. Claude Code does not record silent shift+tab toggles, so we cannot tell whether you pressed shift+tab back into plan mode after those edits.",
		actionHint:
			'Toggle "Lenient" in the filter row to treat this as non-pending.',
	};
};

export const resolveStatusDisplay = (
	status: SessionStatus,
	planPendingInfo: PlanPendingInfo,
	strict: boolean,
): StatusDisplay => {
	const planInference =
		planPendingInfo.confidence === "inferred-stale-plan-entry" &&
		(status === "waiting" || status === "thinking");
	if (strict && planInference) {
		// Strict mode surfaces uncertainty as "unknown" rather than
		// guessing. Lenient mode trusts the base status and decorates
		// it with a "?" suffix (fallthrough below).
		return {
			className: "unknown",
			label: "unknown",
			uncertainty: buildUnknownPlanContent(planPendingInfo),
		};
	}
	if (planInference) {
		return {
			className: `${status} unknown-plan`,
			label: `${status} ?`,
			uncertainty: buildUnknownPlanContent(planPendingInfo),
		};
	}
	return { className: status, label: status, uncertainty: null };
};
