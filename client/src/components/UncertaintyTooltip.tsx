import { useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface UncertaintyContent {
	title: string;
	evidenceRows: Array<{ label: string; value: string }>;
	explanation: string;
	actionHint?: string;
}

interface UncertaintyTooltipProps {
	content: UncertaintyContent;
	anchorRect: DOMRect;
}

function UncertaintyTooltipPortal({
	content,
	anchorRect,
}: UncertaintyTooltipProps) {
	// Portal + fixed positioning so parent `overflow: hidden` can't clip us.
	// Mirrors UsageTooltip to stay consistent with the rest of the dashboard.
	const style: React.CSSProperties = {
		position: "fixed",
		top: anchorRect.bottom + 8,
		left: Math.max(8, Math.min(anchorRect.left, window.innerWidth - 320)),
	};

	return createPortal(
		<div
			className="usage-tooltip uncertainty-tooltip"
			role="tooltip"
			style={style}
		>
			<div className="usage-tooltip-title">{content.title}</div>
			{content.evidenceRows.map((row) => (
				<div key={row.label} className="usage-tooltip-row">
					<span>{row.label}</span>
					<span>{row.value}</span>
				</div>
			))}
			<div className="usage-tooltip-row usage-tooltip-meta uncertainty-explanation">
				{content.explanation}
			</div>
			{content.actionHint && (
				<div className="usage-tooltip-stale uncertainty-action">
					{content.actionHint}
				</div>
			)}
		</div>,
		document.body,
	);
}

interface UncertaintyAnchorProps {
	content: UncertaintyContent | null;
	children: React.ReactNode;
	className?: string;
}

export function UncertaintyAnchor({
	content,
	children,
	className,
}: UncertaintyAnchorProps) {
	const anchorRef = useRef<HTMLSpanElement>(null);
	const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

	const onShow = () => {
		if (!content) return;
		if (anchorRef.current)
			setAnchorRect(anchorRef.current.getBoundingClientRect());
	};
	const onHide = () => setAnchorRect(null);

	return (
		<span
			ref={anchorRef}
			className={className}
			onMouseEnter={onShow}
			onMouseLeave={onHide}
			onFocus={onShow}
			onBlur={onHide}
		>
			{children}
			{content && anchorRect && (
				<UncertaintyTooltipPortal content={content} anchorRect={anchorRect} />
			)}
		</span>
	);
}
