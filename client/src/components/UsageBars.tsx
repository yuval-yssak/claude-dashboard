import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { RateLimitEntry, RateLimits } from "../types";

interface UsageBarsProps {
	rateLimits: RateLimits | null;
}

function fillColor(pct: number): string {
	if (pct >= 95) return "#e74c3c";
	if (pct >= 80) return "#e67e22";
	if (pct >= 50) return "#f1c40f";
	return "#2ecc71";
}

function formatAbsoluteTime(epochSecs: number): string {
	const date = new Date(epochSecs * 1000);
	const now = new Date();
	const timeStr = date.toLocaleTimeString([], {
		hour: "numeric",
		minute: "2-digit",
	});
	if (date.toDateString() === now.toDateString()) return `today at ${timeStr}`;
	const tomorrow = new Date(now);
	tomorrow.setDate(now.getDate() + 1);
	if (date.toDateString() === tomorrow.toDateString())
		return `tomorrow at ${timeStr}`;
	return `${date.toLocaleDateString([], { month: "short", day: "numeric" })} at ${timeStr}`;
}

function formatRelativeDuration(deltaSecs: number): string {
	if (deltaSecs <= 0) return "now";
	const totalMinutes = Math.round(deltaSecs / 60);
	if (totalMinutes < 60) return `${totalMinutes}m`;
	const hours = Math.floor(totalMinutes / 60);
	const minutes = totalMinutes % 60;
	if (hours < 24) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
	const days = Math.floor(hours / 24);
	const remHours = hours % 24;
	return remHours > 0 ? `${days}d ${remHours}h` : `${days}d`;
}

const STATUSLINE_STALE_NOTE =
	"Data is stale — statusline hasn't refreshed recently.";

interface UsageTooltipProps {
	windowLabel: string;
	entry: RateLimitEntry;
	updatedAt: number;
	anchorRect: DOMRect;
	staleNote: string;
}

function UsageTooltip({
	windowLabel,
	entry,
	updatedAt,
	anchorRect,
	staleNote,
}: UsageTooltipProps) {
	const now = Date.now() / 1000;
	const secondsUntilReset = entry.resets_at - now;
	const resetAbsolute = formatAbsoluteTime(entry.resets_at);
	const resetRelative = formatRelativeDuration(secondsUntilReset);
	const updatedAgo = formatRelativeDuration(now - updatedAt);
	// Portal + fixed positioning so parent `overflow: hidden` cannot clip the tooltip.
	const style: React.CSSProperties = {
		position: "fixed",
		top: anchorRect.bottom + 8,
		left: Math.max(8, anchorRect.right - 240),
	};

	return createPortal(
		<div className="usage-tooltip" role="tooltip" style={style}>
			<div className="usage-tooltip-title">{windowLabel} usage</div>
			<div className="usage-tooltip-row">
				<span>Used</span>
				<span>{entry.used_percentage.toFixed(1)}%</span>
			</div>
			<div className="usage-tooltip-row">
				<span>Remaining</span>
				<span>{Math.max(0, 100 - entry.used_percentage).toFixed(1)}%</span>
			</div>
			<div className="usage-tooltip-row">
				<span>Resets</span>
				<span>
					{resetAbsolute} (in {resetRelative})
				</span>
			</div>
			<div className="usage-tooltip-row usage-tooltip-meta">
				<span>Updated</span>
				<span>{updatedAgo} ago</span>
			</div>
			{entry.is_stale && <div className="usage-tooltip-stale">{staleNote}</div>}
		</div>,
		document.body,
	);
}

interface UsageBarProps {
	label: string;
	windowLabel: string;
	entry: RateLimitEntry;
	updatedAt: number;
	staleNote?: string;
}

function UsageBar({
	label,
	windowLabel,
	entry,
	updatedAt,
	staleNote = STATUSLINE_STALE_NOTE,
}: UsageBarProps) {
	const pct = Math.min(100, Math.max(0, entry.used_percentage));
	const staleClass = entry.is_stale ? " usage-bar-stale" : "";
	const groupRef = useRef<HTMLDivElement>(null);
	const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

	const onShowTooltip = () => {
		if (groupRef.current)
			setAnchorRect(groupRef.current.getBoundingClientRect());
	};
	const onHideTooltip = () => setAnchorRect(null);

	return (
		<div
			ref={groupRef}
			className={`usage-bar-group${staleClass}`}
			onMouseEnter={onShowTooltip}
			onMouseLeave={onHideTooltip}
			onFocus={onShowTooltip}
			onBlur={onHideTooltip}
		>
			<span className="usage-bar-label">
				{label}: {Math.round(pct)}%{entry.is_stale ? " (stale)" : ""}
			</span>
			<div className="usage-bar-track">
				<div
					className="usage-bar-fill"
					style={{
						width: `${pct}%`,
						backgroundColor: fillColor(pct),
					}}
				/>
			</div>
			{anchorRect && (
				<UsageTooltip
					windowLabel={windowLabel}
					entry={entry}
					updatedAt={updatedAt}
					anchorRect={anchorRect}
					staleNote={staleNote}
				/>
			)}
		</div>
	);
}

export function UsageBars({ rateLimits }: UsageBarsProps) {
	if (!rateLimits) return null;

	const { five_hour, seven_day, scoped_weeklies, updated_at } = rateLimits;
	if (!five_hour && !seven_day && !scoped_weeklies?.length) return null;

	return (
		<div className="usage-bars">
			{five_hour && (
				<UsageBar
					label="5h"
					windowLabel="5-hour"
					entry={five_hour}
					updatedAt={updated_at}
				/>
			)}
			{seven_day && (
				<UsageBar
					label="7d"
					windowLabel="7-day"
					entry={seven_day}
					updatedAt={updated_at}
				/>
			)}
			{scoped_weeklies?.map((scoped) => (
				<UsageBar
					key={scoped.label}
					label={`${scoped.label} 7d`}
					windowLabel={`${scoped.label} weekly`}
					entry={scoped}
					updatedAt={scoped.updated_at}
					staleNote={`This number may be outdated — Claude Code only refreshes it occasionally. To update it now: open any Claude Code session on this account and run /usage, then the fresh ${scoped.label} weekly value appears here.`}
				/>
			))}
		</div>
	);
}
