import type { ConnectionStatus } from "../hooks/useSSE";

interface HeaderProps {
	generatedAt: string | null;
	connectionStatus: ConnectionStatus;
}

export function Header({ generatedAt, connectionStatus }: HeaderProps) {
	const timeStr = generatedAt ? new Date(generatedAt).toLocaleTimeString() : "";

	const statusLabel =
		connectionStatus === "connected"
			? "Live"
			: connectionStatus === "connecting"
				? "Connecting..."
				: "Disconnected";

	const dotClass = `connection-dot ${connectionStatus}`;

	return (
		<div className="header">
			<h1>
				<span>Claude</span> Sessions Dashboard
			</h1>
			<div className="meta">
				<span className={dotClass} />
				{statusLabel} &middot; {timeStr}
			</div>
		</div>
	);
}
