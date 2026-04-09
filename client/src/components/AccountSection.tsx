import { useCallback } from "react";
import {
	DndContext,
	closestCenter,
	PointerSensor,
	KeyboardSensor,
	TouchSensor,
	useSensor,
	useSensors,
	type DragEndEvent,
	type DragStartEvent,
} from "@dnd-kit/core";
import {
	SortableContext,
	rectSortingStrategy,
	useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { Account, Session } from "../types";
import { SessionCard } from "./SessionCard";
import { useCardOrdering } from "../hooks/useCardOrdering";

interface AccountSectionProps {
	account: Account;
	openPanels: Set<string>;
	loadingSessions: Set<string>;
	onTogglePanel: (sessionId: string) => void;
	onOpenSession: (sessionId: string) => void;
	onNotesChange: (sessionId: string, value: string) => void;
	onNotesFocus: (sessionId: string) => void;
	onNotesBlur: (sessionId: string) => void;
	onToggleTodo: (sessionId: string, index: number, done: boolean) => void;
	onAddTodo: (sessionId: string, text: string) => void;
	onDeleteTodo: (sessionId: string, index: number) => void;
}

interface SortableCardProps {
	session: Session;
	isPinned: boolean;
	isPendingMove: boolean;
	onTogglePin: () => void;
	onMoveCard: (direction: "up" | "down" | "left" | "right") => void;
	onMouseEnter: () => void;
	onMouseLeave: () => void;
	onFocusCapture: () => void;
	onBlurCapture: () => void;
	isOpen: boolean;
	loading: boolean;
	onTogglePanel: () => void;
	onOpenSession: () => void;
	onNotesChange: (v: string) => void;
	onNotesFocus: () => void;
	onNotesBlur: () => void;
	onToggleTodo: (i: number, d: boolean) => void;
	onAddTodo: (t: string) => void;
	onDeleteTodo: (i: number) => void;
}

function SortableCard({
	session,
	isPinned,
	isPendingMove,
	onTogglePin,
	onMoveCard,
	onMouseEnter,
	onMouseLeave,
	onFocusCapture,
	onBlurCapture,
	...cardProps
}: SortableCardProps) {
	const {
		attributes,
		listeners,
		setNodeRef,
		transform,
		transition,
		isDragging,
	} = useSortable({ id: session.session_id });

	// Constrain horizontal movement to prevent overflow on mobile
	const constrainedTransform = transform
		? { ...transform, x: 0 }
		: transform;

	const style: React.CSSProperties = {
		transform: CSS.Transform.toString(constrainedTransform),
		transition,
		zIndex: isDragging ? 10 : undefined,
		opacity: isDragging ? 0.85 : undefined,
	};

	return (
		<div
			ref={setNodeRef}
			style={style}
			onMouseEnter={onMouseEnter}
			onMouseLeave={onMouseLeave}
			onFocusCapture={onFocusCapture}
			onBlurCapture={onBlurCapture}
		>
			<SessionCard
				session={session}
				isPinned={isPinned}
				isPendingMove={isPendingMove}
				onTogglePin={onTogglePin}
				onMoveCard={onMoveCard}
				dragHandleProps={{ ...attributes, ...listeners }}
				{...cardProps}
			/>
		</div>
	);
}

export function AccountSection({
	account,
	openPanels,
	loadingSessions,
	onTogglePanel,
	onOpenSession,
	onNotesChange,
	onNotesFocus,
	onNotesBlur,
	onToggleTodo,
	onAddTodo,
	onDeleteTodo,
}: AccountSectionProps) {
	const {
		orderedSessions,
		pendingMoveIds,
		pinnedIds,
		pinSession,
		unpinSession,
		reorder,
		moveCard,
		setInteractingId,
		setIsDragging,
	} = useCardOrdering(account.sessions, account.config_dir);

	const sensors = useSensors(
		useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
		useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
		useSensor(KeyboardSensor),
	);

	const handleDragStart = useCallback(
		(_event: DragStartEvent) => {
			setIsDragging(true);
		},
		[setIsDragging],
	);

	const handleDragEnd = useCallback(
		(event: DragEndEvent) => {
			setIsDragging(false);
			const { active, over } = event;
			if (over && active.id !== over.id) {
				reorder(String(active.id), String(over.id));
			}
		},
		[reorder, setIsDragging],
	);


	if (account.sessions.length === 0) return null;

	const active = account.sessions.filter(
		(s) =>
			s.status === "thinking" || s.status === "subagent" || s.status === "hook",
	).length;

	const orderedIds = orderedSessions.map((s) => s.session_id);

	return (
		<div className="account">
			<div className="account-header">
				<span className="account-email">{account.email}</span>
				<span className="account-count">
					{account.sessions.length} sessions
					{active ? ` \u00B7 ${active} active` : ""}
				</span>
			</div>
			<DndContext
				sensors={sensors}
				collisionDetection={closestCenter}
				onDragStart={handleDragStart}
				onDragEnd={handleDragEnd}
			>
				<SortableContext
					items={orderedIds}
					strategy={rectSortingStrategy}
				>
					<div className="session-grid">
						{orderedSessions.map((s) => (
							<SortableCard
								key={s.session_id}
								session={s}
								isPinned={pinnedIds.has(s.session_id)}
								isPendingMove={pendingMoveIds.has(s.session_id)}
								onTogglePin={() =>
									pinnedIds.has(s.session_id)
										? unpinSession(s.session_id)
										: pinSession(s.session_id)
								}
								onMoveCard={(dir) => moveCard(s.session_id, dir)}
								onMouseEnter={() => setInteractingId(s.session_id)}
								onMouseLeave={() => setInteractingId(null)}
								onFocusCapture={() => setInteractingId(s.session_id)}
								onBlurCapture={() => setInteractingId(null)}
								isOpen={openPanels.has(s.session_id)}
								loading={loadingSessions.has(s.session_id)}
								onTogglePanel={() => onTogglePanel(s.session_id)}
								onOpenSession={() => onOpenSession(s.session_id)}
								onNotesChange={(v) => onNotesChange(s.session_id, v)}
								onNotesFocus={() => onNotesFocus(s.session_id)}
								onNotesBlur={() => onNotesBlur(s.session_id)}
								onToggleTodo={(i, d) => onToggleTodo(s.session_id, i, d)}
								onAddTodo={(t) => onAddTodo(s.session_id, t)}
								onDeleteTodo={(i) => onDeleteTodo(s.session_id, i)}
							/>
						))}
					</div>
				</SortableContext>
			</DndContext>
		</div>
	);
}
