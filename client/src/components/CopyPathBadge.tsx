import { useRef, useState } from "react";
import { createPortal } from "react-dom";

interface CopyPathBadgeProps {
	sessionId: string;
	jsonlPath: string;
	onCopied: (message: string) => void;
}

export function CopyPathBadge({
	sessionId,
	jsonlPath,
	onCopied,
}: CopyPathBadgeProps) {
	const anchorRef = useRef<HTMLButtonElement>(null);
	const [rect, setRect] = useState<DOMRect | null>(null);

	const onShow = () => {
		if (anchorRef.current) setRect(anchorRef.current.getBoundingClientRect());
	};
	const onHide = () => setRect(null);

	const onCopyClick = async (e: React.MouseEvent) => {
		// Stop propagation so card-level focus/drag handlers don't fire.
		e.stopPropagation();
		await navigator.clipboard.writeText(jsonlPath);
		onCopied("Copied JSONL path");
	};

	return (
		<button
			type="button"
			ref={anchorRef}
			className="jsonl-link"
			data-hint-target=""
			data-hint-scope="card"
			data-hint-card-id={sessionId}
			data-hint-label="Copy JSONL path"
			onMouseEnter={onShow}
			onMouseLeave={onHide}
			onFocus={onShow}
			onBlur={onHide}
			onClick={onCopyClick}
		>
			{sessionId}
			{rect && <CopyPathTooltip rect={rect} jsonlPath={jsonlPath} />}
		</button>
	);
}

interface CopyPathTooltipProps {
	rect: DOMRect;
	jsonlPath: string;
}

function CopyPathTooltip({ rect, jsonlPath }: CopyPathTooltipProps) {
	// Fixed-position portal so card overflow/transform cannot clip us.
	// Mirrors the pattern in UncertaintyAnchor.
	const style: React.CSSProperties = {
		position: "fixed",
		top: rect.bottom + 8,
		left: Math.max(8, Math.min(rect.left, window.innerWidth - 420)),
	};
	return createPortal(
		<div
			className="usage-tooltip copy-path-tooltip"
			role="tooltip"
			style={style}
		>
			<div className="usage-tooltip-title">Click to copy JSONL path</div>
			<div className="copy-path-tooltip-path">{jsonlPath}</div>
		</div>,
		document.body,
	);
}
