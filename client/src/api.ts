import type { UserTodo } from "./types";

export async function saveAnnotation(
	sessionId: string,
	notes: string,
	todos: UserTodo[],
): Promise<void> {
	await fetch(`/api/annotations/${sessionId}`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ notes, todos }),
	});
}

export async function openSession(
	sessionId: string,
): Promise<{ ok: boolean; detail?: string; warning?: string }> {
	const resp = await fetch(`/api/open/${sessionId}`, { method: "POST" });
	return resp.json();
}

export interface PlanFileResponse {
	path: string;
	exists: boolean;
	content: string;
}

export async function fetchPlan(sessionId: string): Promise<PlanFileResponse> {
	const resp = await fetch(`/api/plan/${sessionId}`);
	if (!resp.ok) throw new Error(`plan fetch failed: ${resp.status}`);
	return resp.json();
}
