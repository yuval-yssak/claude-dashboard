import type { UncertaintyContent } from "./components/UncertaintyTooltip";
import type { PermissionModeInfo } from "./types";

export interface ModeDisplay {
	className: string;
	label: string;
	uncertainty: UncertaintyContent | null;
}

const prettyLabel = (mode: string): string =>
	mode === "acceptEdits" ? "accept-edits" : mode;

const confidenceReason = (
	confidence: PermissionModeInfo["confidence"],
): string => {
	switch (confidence) {
		case "inferred-exit-plan":
			return "ExitPlanMode was called earlier in the session — but Claude Code does not record silent shift+tab toggles, so we cannot tell whether you pressed shift+tab back into plan mode after that exit.";
		case "inferred-edits-after-plan":
			return "A permission-mode:plan entry exists but Write/Edit/Bash tool calls happened after it (with no explicit ExitPlanMode). Either the plan was approved via those edits, or you silently shift+tab'd back into plan mode after the edits — the JSONL cannot distinguish the two.";
		case "inferred-plan-at-tail":
			return "The plan-mode entry is at the tail with ambiguous signals after it.";
		default:
			return "";
	}
};

const buildEvidenceRows = (
	info: PermissionModeInfo,
): Array<{ label: string; value: string }> => {
	const e = info.evidence;
	const rows: Array<{ label: string; value: string }> = [];
	if (e.last_permission_mode_entry) {
		rows.push({
			label: "JSONL entry",
			value: `permission-mode:${e.last_permission_mode_entry}`,
		});
	}
	rows.push({
		label: "Lines since entry",
		value: String(e.lines_since_entry),
	});
	const signals: string[] = [];
	if (e.exit_plan_mode_seen_after) signals.push("ExitPlanMode");
	if (e.edit_tools_seen_after) signals.push("Write/Edit/Bash");
	if (e.enter_plan_mode_seen_after) signals.push("EnterPlanMode");
	if (signals.length) {
		rows.push({ label: "Signals after", value: signals.join(", ") });
	}
	if (info.inferred) {
		rows.push({
			label: "Lenient would show",
			value: `${prettyLabel(info.inferred)} mode`,
		});
	}
	return rows;
};

const buildUnknownContent = (info: PermissionModeInfo): UncertaintyContent => ({
	title: "Mode: unknown",
	evidenceRows: buildEvidenceRows(info),
	explanation: confidenceReason(info.confidence),
	actionHint: 'Toggle "Lenient" in the filter row to trust the inference.',
});

export const resolveModeDisplay = (
	info: PermissionModeInfo,
	strict: boolean,
): ModeDisplay | null => {
	if (info.confidence === "none") return null;
	if (info.confidence === "observed") {
		const mode = info.observed;
		if (!mode || mode === "default") return null;
		return {
			className: mode,
			label: `${prettyLabel(mode)} mode`,
			uncertainty: null,
		};
	}
	// Inferred paths.
	if (strict) {
		// Compact inline hint: show the root-cause entry and how many lines
		// have followed, so the user can triage without hovering.
		const entry = info.evidence.last_permission_mode_entry ?? "?";
		const since = info.evidence.lines_since_entry;
		return {
			className: "unknown",
			label: `mode: ? (${entry} +${since})`,
			uncertainty: buildUnknownContent(info),
		};
	}
	const guess = info.inferred;
	if (!guess || guess === "default") return null;
	return {
		className: guess,
		label: `${prettyLabel(guess)} mode`,
		uncertainty: null,
	};
};
