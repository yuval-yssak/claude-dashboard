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

		return () => {
			es.close();
			setStatus("disconnected");
		};
	}, [eventName]);

	return status;
}
