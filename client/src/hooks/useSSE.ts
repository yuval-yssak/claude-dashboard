import { useEffect, useRef, useState } from "react";

export type ConnectionStatus = "connected" | "connecting" | "disconnected";

export function useSSE<T>(
	eventName: string,
	onData: (data: T) => void,
): ConnectionStatus {
	const [status, setStatus] = useState<ConnectionStatus>("connecting");
	const onDataRef = useRef(onData);
	onDataRef.current = onData;

	useEffect(() => {
		const es = new EventSource("/api/events");

		es.addEventListener(eventName, (e) => {
			try {
				const parsed = JSON.parse(e.data) as T;
				onDataRef.current(parsed);
			} catch {
				// ignore parse errors
			}
		});

		es.onopen = () => setStatus("connected");

		es.onerror = () => {
			// EventSource auto-reconnects; show disconnected while retrying
			if (es.readyState === EventSource.CLOSED) {
				setStatus("disconnected");
			} else {
				setStatus("connecting");
			}
		};

		// When the tab is backgrounded, browsers throttle or drop SSE
		// connections.  Fetch fresh data when the tab becomes visible again
		// so the UI isn't stuck on a stale snapshot.
		const onVisible = () => {
			if (document.visibilityState !== "visible") return;
			fetch("/api/sessions")
				.then((r) => r.json())
				.then((d) => onDataRef.current(d as T))
				.catch(() => {});
		};
		document.addEventListener("visibilitychange", onVisible);

		return () => {
			es.close();
			document.removeEventListener("visibilitychange", onVisible);
			setStatus("disconnected");
		};
	}, [eventName]);

	return status;
}
