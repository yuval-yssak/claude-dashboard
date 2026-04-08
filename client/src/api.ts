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
): Promise<{ ok: boolean; detail?: string }> {
	const resp = await fetch(`/api/open/${sessionId}`, { method: "POST" });
	return resp.json();
}
