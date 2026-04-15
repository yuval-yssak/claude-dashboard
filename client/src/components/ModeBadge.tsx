import { resolveModeDisplay } from "../modeDisplay";
import type { PermissionModeInfo } from "../types";
import { UncertaintyAnchor } from "./UncertaintyTooltip";

interface ModeBadgeProps {
	info: PermissionModeInfo;
	strict: boolean;
}

export function ModeBadge({ info, strict }: ModeBadgeProps) {
	const display = resolveModeDisplay(info, strict);
	if (!display) return null;
	return (
		<UncertaintyAnchor
			content={display.uncertainty}
			className={`mode-badge mode-${display.className}`}
		>
			{display.label}
		</UncertaintyAnchor>
	);
}
