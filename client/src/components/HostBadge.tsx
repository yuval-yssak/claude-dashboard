import type { HostId, SessionHost } from "../types";

interface HostBadgeProps {
	host: SessionHost | null;
}

// Minimal monochrome glyphs. Real product logos require trademark
// permission; these are simple letterforms that read at 14px and
// stay legible on both light and dark card backgrounds.
const HOST_GLYPHS: Record<HostId, string> = {
	warp: "W",
	iterm2: "i",
	terminal: ">_",
	"claude-desktop": "C",
	"vscode-terminal": "VS",
	"vscode-extension": "VS",
	"jetbrains-terminal": "JB",
	"jetbrains-extension": "JB",
};

type HostVariant = "terminal" | "ide-terminal" | "ide-extension" | "desktop";

const HOST_VARIANT: Record<HostId, HostVariant> = {
	warp: "terminal",
	iterm2: "terminal",
	terminal: "terminal",
	"claude-desktop": "desktop",
	"vscode-terminal": "ide-terminal",
	"vscode-extension": "ide-extension",
	"jetbrains-terminal": "ide-terminal",
	"jetbrains-extension": "ide-extension",
};

export function HostBadge({ host }: HostBadgeProps) {
	if (!host) return null;
	const variant = HOST_VARIANT[host.id];
	const glyph = HOST_GLYPHS[host.id];
	return (
		<span
			role="img"
			aria-label={`Host: ${host.label}`}
			className={`host-badge host-${host.id} host-variant-${variant}`}
			data-host-tooltip={`Running in ${host.label}`}
		>
			{glyph}
		</span>
	);
}
