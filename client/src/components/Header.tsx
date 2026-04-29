import type { ConnectionStatus } from "../hooks/useSSE";

interface HeaderProps {
	generatedAt: string | null;
	connectionStatus: ConnectionStatus;
	pipSupported: boolean;
	pipActive: boolean;
	pipReopenPending: boolean;
	onTogglePip: () => void;
}

export function Header({
	generatedAt,
	connectionStatus,
	pipSupported,
	pipActive,
	pipReopenPending,
	onTogglePip,
}: HeaderProps) {
	const timeStr = generatedAt ? new Date(generatedAt).toLocaleTimeString() : "";

	const statusLabel =
		connectionStatus === "connected"
			? "Live"
			: connectionStatus === "connecting"
				? "Connecting..."
				: "Disconnected";

	const dotClass = `connection-dot ${connectionStatus}`;
	const pipBtnClass = `pip-toggle${pipActive ? " active" : ""}${pipReopenPending ? " reopen-pending" : ""}`;
	const pipBtnTitle = pipActive
		? "Close picture-in-picture mini dashboard"
		: pipReopenPending
			? "Click to reopen picture-in-picture (was open before reload)"
			: "Open picture-in-picture mini dashboard";

	return (
		<div className="header">
			<h1>
				<span>Claude</span> Sessions Dashboard
			</h1>
			<div className="meta">
				{pipSupported && (
					<button
						type="button"
						className={pipBtnClass}
						onClick={onTogglePip}
						title={pipBtnTitle}
						data-hint-target=""
						data-hint-scope="outline"
					>
						<svg
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
							strokeLinejoin="round"
							role="img"
							aria-label="picture in picture"
						>
							<title>picture in picture</title>
							<rect x="3" y="5" width="18" height="14" rx="2" />
							<rect
								x="12"
								y="11"
								width="7"
								height="6"
								rx="1"
								fill="currentColor"
							/>
						</svg>
						<span>PiP</span>
					</button>
				)}
				<span className={dotClass} />
				{statusLabel} &middot; {timeStr}
			</div>
		</div>
	);
}
