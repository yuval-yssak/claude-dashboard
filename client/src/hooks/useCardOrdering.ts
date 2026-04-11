import { useState, useRef, useCallback, useEffect } from "react";
import type { Session, LayoutPreferences } from "../types";

const STORAGE_KEY = "dashboard-card-layout";
const PENDING_DELAY_MS = 2500;

function loadLayout(): LayoutPreferences {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw) return JSON.parse(raw);
	} catch {}
	return { positions: {} };
}

function saveLayout(layout: LayoutPreferences) {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
	} catch {}
}

/** Move all pinned IDs to the front, preserving relative order among pinned
 *  and among unpinned cards. */
function applyPinnedToTop(order: string[], pinned: Set<string>): string[] {
	if (pinned.size === 0) return order;
	const top: string[] = [];
	const rest: string[] = [];
	for (const id of order) {
		if (pinned.has(id)) top.push(id);
		else rest.push(id);
	}
	return [...top, ...rest];
}

export function useCardOrdering(sessions: Session[], accountId: string) {
	const [displayOrder, setDisplayOrder] = useState<string[]>([]);
	const [pendingMoveIds, setPendingMoveIds] = useState<Set<string>>(
		new Set(),
	);
	const [pinnedIds, setPinnedIds] = useState<Set<string>>(() => {
		const layout = loadLayout();
		const acct = layout.positions[accountId] || {};
		return new Set(
			Object.entries(acct)
				.filter(([, v]) => v.pinned)
				.map(([k]) => k),
		);
	});

	const interactingIdRef = useRef<string | null>(null);
	const pendingTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(
		new Map(),
	);
	const serverOrderRef = useRef<string[]>([]);
	const isDraggingRef = useRef(false);
	// Tracks the user's intended order — set after drag/keyboard move.
	// When set, the pending-move system respects it for ALL cards.
	const userOrderRef = useRef<string[] | null>(null);

	const serverOrder = sessions.map((s) => s.session_id);

	// On first render or when sessions list changes (add/remove), sync display order
	useEffect(() => {
		setDisplayOrder((prev) => {
			if (prev.length === 0) return applyPinnedToTop(serverOrder, pinnedIds);

			const prevSet = new Set(prev);
			const serverSet = new Set(serverOrder);
			const added = serverOrder.filter((id) => !prevSet.has(id));
			const kept = prev.filter((id) => serverSet.has(id));

			if (added.length === 0 && kept.length === prev.length) {
				return prev;
			}

			if (userOrderRef.current) {
				const keptUser = userOrderRef.current.filter((id) => serverSet.has(id));
				userOrderRef.current = [...keptUser, ...added];
			}

			return applyPinnedToTop([...kept, ...added], pinnedIds);
		});
		serverOrderRef.current = serverOrder;
	}, [serverOrder.join(",")]);

	// Detect server reorder and schedule pending moves.
	useEffect(() => {
		if (displayOrder.length === 0) return;

		const newServerOrder = serverOrderRef.current;
		const pendingUpdates: string[] = [];

		for (let i = 0; i < newServerOrder.length; i++) {
			const id = newServerOrder[i];
			const currentIdx = displayOrder.indexOf(id);
			if (currentIdx === -1) continue;
			// Pinned cards stay at top, never moved by server
			if (pinnedIds.has(id)) continue;
			// If the user has set a custom order, respect it for ALL cards
			if (userOrderRef.current) continue;

			const serverIdx = i;
			// Account for pinned cards shifting indices:
			// server doesn't know about pinned-to-top, so adjust
			const pinnedCount = [...pinnedIds].filter((pid) =>
				displayOrder.indexOf(pid) < displayOrder.indexOf(id),
			).length;
			const adjustedServerIdx = serverIdx + pinnedCount;

			if (currentIdx !== adjustedServerIdx && !pendingTimersRef.current.has(id)) {
				pendingUpdates.push(id);
			}
		}

		if (pendingUpdates.length === 0) return;

		setPendingMoveIds((prev) => {
			const next = new Set(prev);
			for (const id of pendingUpdates) next.add(id);
			return next;
		});

		for (const id of pendingUpdates) {
			const timer = setTimeout(() => {
				pendingTimersRef.current.delete(id);

				if (interactingIdRef.current === id) {
					const retryTimer = setTimeout(() => {
						pendingTimersRef.current.delete(id);
						applyServerOrder(id);
					}, 1000);
					pendingTimersRef.current.set(id, retryTimer);
					return;
				}

				applyServerOrder(id);
			}, PENDING_DELAY_MS);
			pendingTimersRef.current.set(id, timer);
		}

		return () => {};
	}, [serverOrder.join(","), displayOrder.join(","), pinnedIds]);

	const applyServerOrder = useCallback(
		(specificId?: string) => {
			setDisplayOrder((prev) => {
				const server = serverOrderRef.current;
				if (specificId) {
					const filtered = prev.filter((id) => id !== specificId);
					const serverIdx = server.indexOf(specificId);
					const insertIdx = Math.min(serverIdx, filtered.length);
					filtered.splice(insertIdx, 0, specificId);
					// Re-apply pin order so pinned cards are never displaced by server reorders
					return applyPinnedToTop(filtered, pinnedIds);
				}
				return server;
			});
			setPendingMoveIds((prev) => {
				if (!specificId) return new Set();
				const next = new Set(prev);
				next.delete(specificId);
				return next;
			});
		},
		[pinnedIds],
	);

	// Cancel pending move if card is already at the right position
	useEffect(() => {
		if (pendingMoveIds.size === 0) return;

		const server = serverOrderRef.current;
		const toCancel: string[] = [];

		for (const id of pendingMoveIds) {
			const currentIdx = displayOrder.indexOf(id);
			const serverIdx = server.indexOf(id);
			if (currentIdx === serverIdx) {
				toCancel.push(id);
			}
		}

		if (toCancel.length > 0) {
			setPendingMoveIds((prev) => {
				const next = new Set(prev);
				for (const id of toCancel) {
					next.delete(id);
					const timer = pendingTimersRef.current.get(id);
					if (timer) {
						clearTimeout(timer);
						pendingTimersRef.current.delete(id);
					}
				}
				return next;
			});
		}
	}, [serverOrder.join(","), displayOrder.join(","), pendingMoveIds]);

	const pinSession = useCallback(
		(id: string) => {
			setPinnedIds((prev) => {
				const next = new Set(prev);
				next.add(id);
				const layout = loadLayout();
				if (!layout.positions[accountId]) layout.positions[accountId] = {};
				layout.positions[accountId][id] = { index: 0, pinned: true };
				saveLayout(layout);
				return next;
			});
			// Move to top immediately
			setDisplayOrder((prev) => {
				const filtered = prev.filter((i) => i !== id);
				return [id, ...filtered];
			});
			// Cancel any pending move
			const timer = pendingTimersRef.current.get(id);
			if (timer) {
				clearTimeout(timer);
				pendingTimersRef.current.delete(id);
			}
			setPendingMoveIds((prev) => {
				const next = new Set(prev);
				next.delete(id);
				return next;
			});
		},
		[accountId],
	);

	const unpinSession = useCallback(
		(id: string) => {
			setPinnedIds((prev) => {
				const next = new Set(prev);
				next.delete(id);
				const layout = loadLayout();
				if (layout.positions[accountId]?.[id]) {
					delete layout.positions[accountId][id];
				}
				saveLayout(layout);
				return next;
			});
			// Card stays where it is but will be subject to server reorder
		},
		[accountId],
	);

	const reorder = useCallback(
		(activeId: string, overId: string) => {
			setDisplayOrder((prev) => {
				const oldIdx = prev.indexOf(activeId);
				const newIdx = prev.indexOf(overId);
				if (oldIdx === -1 || newIdx === -1) return prev;
				const next = [...prev];
				next.splice(oldIdx, 1);
				next.splice(newIdx, 0, activeId);
				userOrderRef.current = next;
				return next;
			});
			setPendingMoveIds((prev) => {
				const next = new Set(prev);
				next.delete(activeId);
				return next;
			});
			const timer = pendingTimersRef.current.get(activeId);
			if (timer) {
				clearTimeout(timer);
				pendingTimersRef.current.delete(activeId);
			}
		},
		[],
	);

	const moveCard = useCallback(
		(id: string, direction: "up" | "down" | "left" | "right") => {
			setDisplayOrder((prev) => {
				const idx = prev.indexOf(id);
				if (idx === -1) return prev;
				let newIdx = idx;
				if (direction === "up" || direction === "left") {
					newIdx = Math.max(0, idx - 1);
				} else {
					newIdx = Math.min(prev.length - 1, idx + 1);
				}
				if (newIdx === idx) return prev;
				const next = [...prev];
				next.splice(idx, 1);
				next.splice(newIdx, 0, id);
				userOrderRef.current = next;
				return next;
			});
		},
		[],
	);

	const setInteractingId = useCallback((id: string | null) => {
		interactingIdRef.current = id;
	}, []);

	const setIsDragging = useCallback((dragging: boolean) => {
		isDraggingRef.current = dragging;
	}, []);

	// Build ordered sessions from displayOrder
	const sessionMap = new Map(sessions.map((s) => [s.session_id, s]));
	const orderedSessions = displayOrder
		.map((id) => sessionMap.get(id))
		.filter((s): s is Session => s != null);

	if (orderedSessions.length < sessions.length) {
		const inOrder = new Set(displayOrder);
		for (const s of sessions) {
			if (!inOrder.has(s.session_id)) {
				orderedSessions.push(s);
			}
		}
	}

	return {
		orderedSessions,
		pendingMoveIds,
		pinnedIds,
		isDraggingRef,
		pinSession,
		unpinSession,
		reorder,
		moveCard,
		setInteractingId,
		setIsDragging,
	};
}
