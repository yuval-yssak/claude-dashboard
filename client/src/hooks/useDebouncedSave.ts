import { useCallback, useEffect, useRef } from "react";

export function useDebouncedSave() {
	const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

	useEffect(() => {
		return () => {
			for (const t of timers.current.values()) clearTimeout(t);
		};
	}, []);

	return useCallback((key: string, fn: () => void, ms = 400) => {
		const existing = timers.current.get(key);
		if (existing) clearTimeout(existing);
		timers.current.set(key, setTimeout(fn, ms));
	}, []);
}
