import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { HintAssignment, HintState } from "../hooks/useHintMode";

interface HintOverlayProps {
	state: HintState;
	computeAssignments: () => HintAssignment[];
	assignmentsRef: React.MutableRefObject<HintAssignment[]>;
	refresh: () => void;
}

interface RenderedHint {
	id: string;
	label: string;
	top: number;
	left: number;
	dimmed: boolean;
	tooltip: string;
}

const describeTarget = (element: HTMLElement): string => {
	// Priority: explicit data-hint-label (component-curated) > title > aria-label > placeholder.
	// We do NOT fall back to textContent — for container elements it pulls in
	// the entire visible body. Components should set data-hint-label when no
	// title/aria-label fits the hint context.
	const hintLabel = element.dataset.hintLabel;
	if (hintLabel?.trim()) return hintLabel.trim();
	const title = element.getAttribute("title");
	if (title?.trim()) return title.trim();
	const ariaLabel = element.getAttribute("aria-label");
	if (ariaLabel?.trim()) return ariaLabel.trim();
	const placeholder = element.getAttribute("placeholder");
	if (placeholder?.trim()) return placeholder.trim();
	return "Activate";
};

const buildTooltip = (element: HTMLElement, label: string): string => {
	const description = describeTarget(element);
	return `${description} — press ${label.toUpperCase()}`;
};

// When a pill sits near a viewport edge, anchor its tooltip to the same edge
// so it doesn't get clipped. The threshold is generous enough to cover most
// tooltip widths without per-pill measurement.
const EDGE_THRESHOLD_PX = 220;
const edgeClass = (pillLeft: number): string => {
	if (pillLeft < EDGE_THRESHOLD_PX) return "tooltip-anchor-left";
	if (pillLeft > window.innerWidth - EDGE_THRESHOLD_PX) {
		return "tooltip-anchor-right";
	}
	return "";
};

const buildRenderedHints = (
	assignments: HintAssignment[],
	partial: string,
): RenderedHint[] => {
	return assignments.map((a, i) => {
		const rect = a.element.getBoundingClientRect();
		// Slight nudge above-left so hint sits at top-left corner of target,
		// outside the target's content area.
		return {
			id: `${i}-${a.label}`,
			label: a.label,
			top: rect.top - 2,
			left: rect.left - 2,
			dimmed: Boolean(partial) && !a.label.startsWith(partial),
			tooltip: buildTooltip(a.element, a.label),
		};
	});
};

export function HintOverlay({
	state,
	computeAssignments,
	assignmentsRef,
	refresh,
}: HintOverlayProps) {
	const [hints, setHints] = useState<RenderedHint[]>([]);
	const rafRef = useRef<number | null>(null);

	const recompute = () => {
		if (state.suppressed) {
			assignmentsRef.current = [];
			setHints([]);
			return;
		}
		const assignments = computeAssignments();
		assignmentsRef.current = assignments;
		setHints(buildRenderedHints(assignments, state.partial));
	};

	// recompute reads stable refs and helpers; only state changes should drive it.
	// biome-ignore lint/correctness/useExhaustiveDependencies: deps intentional
	useLayoutEffect(() => {
		recompute();
	}, [
		state.mode,
		state.activeCardId,
		state.partial,
		state.suppressed,
		state.version,
	]);

	// assignmentsRef is a ref by design; only state.partial drives re-binding.
	// biome-ignore lint/correctness/useExhaustiveDependencies: ref intentional
	useEffect(() => {
		// Re-position on scroll/resize without recomputing assignments.
		const reposition = () => {
			if (rafRef.current !== null) return;
			rafRef.current = requestAnimationFrame(() => {
				rafRef.current = null;
				setHints(buildRenderedHints(assignmentsRef.current, state.partial));
			});
		};
		window.addEventListener("scroll", reposition, {
			passive: true,
			capture: true,
		});
		window.addEventListener("resize", reposition);
		return () => {
			window.removeEventListener("scroll", reposition, { capture: true });
			window.removeEventListener("resize", reposition);
			if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
		};
	}, [state.partial]);

	useEffect(() => {
		// Watch the document for added/removed hint targets (SSE re-renders, modal opens).
		const observer = new MutationObserver(() => refresh());
		observer.observe(document.body, {
			childList: true,
			subtree: true,
			attributes: true,
			attributeFilter: [
				"data-hint-target",
				"data-hint-scope",
				"data-hint-card-id",
			],
		});
		return () => observer.disconnect();
	}, [refresh]);

	if (hints.length === 0) return null;

	return createPortal(
		<div className="hint-overlay" aria-hidden="true">
			{hints.map((h) => (
				<span
					key={h.id}
					className={`hint-label${h.dimmed ? " dimmed" : ""} ${edgeClass(h.left)}`}
					style={{ top: h.top, left: h.left }}
					data-tooltip={h.tooltip}
				>
					{h.label}
				</span>
			))}
		</div>,
		document.body,
	);
}
