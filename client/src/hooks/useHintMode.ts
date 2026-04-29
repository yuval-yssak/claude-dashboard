import { useCallback, useEffect, useRef, useState } from "react";

export type HintMode = "outline" | "card";

export interface HintAssignment {
	element: HTMLElement;
	label: string;
}

export interface HintState {
	mode: HintMode;
	activeCardId: string | null;
	partial: string;
	suppressed: boolean;
	version: number;
}

const HINT_ALPHABET = "asdfghjklqwertyuiopzxcvbnm";
// Per design: ≤20 targets use single letters; switch the entire page to
// two-letter hints once we exceed 20. Not 26 — the user wants a predictable
// "above 20 = two letters everywhere" threshold.
const SINGLE_LETTER_LIMIT = 20;

const isEditableElement = (element: Element | null): boolean => {
	if (!element || !(element instanceof HTMLElement)) return false;
	if (element.isContentEditable) return true;
	const tag = element.tagName;
	if (tag === "TEXTAREA") return true;
	if (tag === "INPUT") {
		const type = (element as HTMLInputElement).type;
		// Buttons and similar non-text inputs don't capture typing.
		const nonTextTypes = [
			"button",
			"submit",
			"reset",
			"checkbox",
			"radio",
			"file",
		];
		return !nonTextTypes.includes(type);
	}
	return false;
};

const isInsideDialog = (element: Element | null): boolean => {
	if (!element) return false;
	return Boolean(element.closest('[role="dialog"]'));
};

const isInsideHintSuppress = (element: Element | null): boolean => {
	if (!element) return false;
	return Boolean(element.closest('[data-hint-suppress="true"]'));
};

const isAnyDialogOpen = (): boolean => {
	// Plan/notes modals don't always autofocus into themselves on open, so
	// activeElement may stay on <body> while a modal is visibly on top. Detect
	// by DOM presence rather than focus alone.
	// We do NOT include [data-hint-suppress="true"] here — that attribute is
	// for elements that should suppress hints only when focused (e.g., the
	// drag handle in keyboard mode). Suppression by focus is handled below.
	return Boolean(document.querySelector('[role="dialog"]'));
};

const computeSuppressed = (): boolean => {
	const active = document.activeElement;
	return (
		isEditableElement(active) ||
		isInsideDialog(active) ||
		isInsideHintSuppress(active) ||
		isAnyDialogOpen()
	);
};

const collectTargets = (
	mode: HintMode,
	activeCardId: string | null,
): HTMLElement[] => {
	const scope = mode === "outline" ? "outline" : "card";
	const selector =
		mode === "outline"
			? '[data-hint-target][data-hint-scope="outline"]'
			: `[data-hint-target][data-hint-scope="card"][data-hint-card-id="${activeCardId}"]`;
	const all = Array.from(document.querySelectorAll<HTMLElement>(selector));
	// Filter out elements with zero-size bounding boxes (hidden / display:none).
	return all.filter((el) => {
		const rect = el.getBoundingClientRect();
		return rect.width > 0 && rect.height > 0 && el.dataset.hintScope === scope;
	});
};

const assignLabels = (targets: HTMLElement[]): HintAssignment[] => {
	if (targets.length === 0) return [];
	const useTwoLetter = targets.length > SINGLE_LETTER_LIMIT;
	if (!useTwoLetter) {
		return targets.map((element, i) => ({
			element,
			label: HINT_ALPHABET[i],
		}));
	}
	// Two-letter: walk pairs (aa, ab, ac, ...). 26*26 = 676 — far more than we'll ever need.
	const pairs: string[] = [];
	for (const first of HINT_ALPHABET) {
		for (const second of HINT_ALPHABET) {
			pairs.push(first + second);
			if (pairs.length >= targets.length) break;
		}
		if (pairs.length >= targets.length) break;
	}
	return targets.map((element, i) => ({ element, label: pairs[i] }));
};

const triggerHintAction = (element: HTMLElement, onAfter: () => void) => {
	// Inputs and any element with data-hint-action="focus" (e.g., the drag
	// handle, which then receives Space/arrow events from dnd-kit's keyboard
	// sensor) get focused instead of clicked.
	const wantsFocus =
		isEditableElement(element) || element.dataset.hintAction === "focus";
	if (wantsFocus) {
		element.scrollIntoView({ block: "nearest", behavior: "smooth" });
		element.focus();
		// Programmatic .focus() should fire focusin in real browsers, but we
		// also call refresh() so the overlay re-derives suppression even in
		// edge cases where focusin doesn't fire (synthetic events, frame loss).
		onAfter();
		return;
	}
	element.click();
	onAfter();
};

export const useHintMode = () => {
	const [state, setState] = useState<HintState>({
		mode: "outline",
		activeCardId: null,
		partial: "",
		suppressed: computeSuppressed(),
		version: 0,
	});

	const stateRef = useRef(state);
	stateRef.current = state;

	const assignmentsRef = useRef<HintAssignment[]>([]);

	const refresh = useCallback(() => {
		// Re-derive suppression on every refresh — the DOM may have changed
		// (modal opened/closed, input focused) without firing focusin/focusout.
		const nextSuppressed = computeSuppressed();
		setState((prev) =>
			prev.suppressed === nextSuppressed
				? { ...prev, version: prev.version + 1 }
				: { ...prev, suppressed: nextSuppressed, version: prev.version + 1 },
		);
	}, []);

	const computeAssignments = useCallback((): HintAssignment[] => {
		// Always re-check suppression at compute time — the source of truth is
		// the current DOM, not the cached state flag.
		if (computeSuppressed()) return [];
		const { mode, activeCardId } = stateRef.current;
		const targets = collectTargets(mode, activeCardId);
		return assignLabels(targets);
	}, []);

	const enterCardMode = useCallback((cardId: string) => {
		setState((prev) => ({
			...prev,
			mode: "card",
			activeCardId: cardId,
			partial: "",
			version: prev.version + 1,
		}));
	}, []);

	const exitCardMode = useCallback(() => {
		setState((prev) => ({
			...prev,
			mode: "outline",
			activeCardId: null,
			partial: "",
			version: prev.version + 1,
		}));
	}, []);

	const handleLetter = useCallback<(key: string) => void>(
		(key: string) => {
			const assignments = assignmentsRef.current;
			if (assignments.length === 0) return;
			const useTwoLetter = assignments[0].label.length === 2;
			const current = stateRef.current;
			const candidate = current.partial + key;

			if (!useTwoLetter) {
				const match = assignments.find((a) => a.label === candidate);
				if (!match) {
					// Unknown letter — clear any partial; in single-letter mode partial should already be "".
					setState((prev) => ({ ...prev, partial: "" }));
					return;
				}
				const cardId = match.element.dataset.hintCardId;
				if (current.mode === "outline" && cardId) {
					enterCardMode(cardId);
					return;
				}
				triggerHintAction(match.element, refresh);
				if (current.mode === "card") exitCardMode();
				return;
			}

			// Two-letter mode.
			if (candidate.length === 1) {
				// First letter — only accept if it's a valid prefix.
				const hasPrefix = assignments.some((a) =>
					a.label.startsWith(candidate),
				);
				setState((prev) => ({ ...prev, partial: hasPrefix ? candidate : "" }));
				return;
			}
			// Second letter — must be a complete match or reset.
			const match = assignments.find((a) => a.label === candidate);
			if (!match) {
				setState((prev) => ({ ...prev, partial: "" }));
				return;
			}
			const cardId = match.element.dataset.hintCardId;
			setState((prev) => ({ ...prev, partial: "" }));
			if (current.mode === "outline" && cardId) {
				enterCardMode(cardId);
				return;
			}
			triggerHintAction(match.element, refresh);
			if (current.mode === "card") exitCardMode();
		},
		[enterCardMode, exitCardMode, refresh],
	);

	const handleEscape = useCallback(() => {
		const current = stateRef.current;
		// If a dialog is in focus, leave Escape entirely to the modal's own handler.
		// Otherwise we'd both close the modal AND exit card mode on a single press.
		if (isInsideDialog(document.activeElement)) return;
		// Editable focus: blur it. focusout listener will clear `suppressed` and hints reappear.
		if (isEditableElement(document.activeElement)) {
			(document.activeElement as HTMLElement).blur();
			refresh();
			return;
		}
		// data-hint-suppress focus (e.g., drag handle in keyboard mode but not
		// yet picked up): blur to release. dnd-kit only consumes Esc while a
		// drag is active; if we don't blur here, Esc would do nothing visible.
		const suppressEl = document.activeElement?.closest(
			'[data-hint-suppress="true"]',
		);
		if (suppressEl) {
			(suppressEl as HTMLElement).blur();
			refresh();
			return;
		}
		// Partial typed: clear it.
		if (current.partial) {
			setState((prev) => ({ ...prev, partial: "" }));
			return;
		}
		// Card mode: back to outline.
		if (current.mode === "card") {
			exitCardMode();
			return;
		}
		// Outline + no partial: no-op.
	}, [exitCardMode, refresh]);

	const handleBackspace = useCallback(() => {
		const current = stateRef.current;
		if (current.partial) {
			setState((prev) => ({ ...prev, partial: "" }));
		}
	}, []);

	useEffect(() => {
		const onKeyDown = (e: KeyboardEvent) => {
			// Every keydown re-syncs suppression from document.activeElement.
			// focusin/focusout aren't always reliable (e.g., after programmatic
			// focus changes), and the user types only when something is focused,
			// so this is a robust single source of truth for visual state.
			const nowSuppressed = computeSuppressed();
			if (nowSuppressed !== stateRef.current.suppressed) {
				setState((prev) => ({ ...prev, suppressed: nowSuppressed }));
			}
			if (e.key === "Escape") {
				handleEscape();
				return;
			}
			if (nowSuppressed) return;
			if (e.key === "Backspace") {
				handleBackspace();
				return;
			}
			// Ignore modified keys so we don't intercept Cmd+R, Ctrl+ArrowLeft (card-move), etc.
			if (e.metaKey || e.ctrlKey || e.altKey) return;
			if (e.key.length !== 1) return;
			const lower = e.key.toLowerCase();
			if (!HINT_ALPHABET.includes(lower)) return;
			e.preventDefault();
			handleLetter(lower);
		};
		window.addEventListener("keydown", onKeyDown);
		return () => window.removeEventListener("keydown", onKeyDown);
	}, [handleEscape, handleBackspace, handleLetter]);

	useEffect(() => {
		const onFocusChange = () => {
			const next = computeSuppressed();
			setState((prev) =>
				prev.suppressed === next ? prev : { ...prev, suppressed: next },
			);
		};
		document.addEventListener("focusin", onFocusChange);
		document.addEventListener("focusout", onFocusChange);
		return () => {
			document.removeEventListener("focusin", onFocusChange);
			document.removeEventListener("focusout", onFocusChange);
		};
	}, []);

	// state.version forces this to re-check after every DOM-mutation refresh,
	// even when mode/activeCardId values haven't changed.
	// biome-ignore lint/correctness/useExhaustiveDependencies: version intentional
	useEffect(() => {
		if (state.mode !== "card" || !state.activeCardId) return;
		const stillExists = document.querySelector(
			`[data-hint-card-id="${state.activeCardId}"]`,
		);
		if (!stillExists) exitCardMode();
	}, [state.mode, state.activeCardId, state.version, exitCardMode]);

	return {
		state,
		computeAssignments,
		assignmentsRef,
		refresh,
	};
};
