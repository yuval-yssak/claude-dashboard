import { useCallback, useEffect, useRef, useState } from "react";

interface DocumentPipOptions {
	width: number;
	height: number;
}

interface DocumentPipApi {
	requestWindow: (options: DocumentPipOptions) => Promise<Window>;
	window: Window | null;
}

const getPipApi = (): DocumentPipApi | null => {
	const w = window as unknown as { documentPictureInPicture?: DocumentPipApi };
	return w.documentPictureInPicture ?? null;
};

const REOPEN_FLAG = "dashboard-pip-reopen";

export const isDocumentPipSupported = (): boolean => getPipApi() !== null;

const cloneStylesIntoPip = (pipDoc: Document) => {
	// Snapshot stylesheets at open time. The PiP document starts empty, and live
	// adoption of <style>/<link> is unreliable across Chrome versions, so we
	// copy linked stylesheets as <link> and inline <style> nodes verbatim.
	const head = pipDoc.head;
	for (const sheet of Array.from(document.styleSheets)) {
		try {
			if (sheet.href) {
				const link = pipDoc.createElement("link");
				link.rel = "stylesheet";
				link.href = sheet.href;
				head.appendChild(link);
				continue;
			}
			const rules = Array.from(sheet.cssRules)
				.map((r) => r.cssText)
				.join("\n");
			const style = pipDoc.createElement("style");
			style.textContent = rules;
			head.appendChild(style);
		} catch {
			// Cross-origin stylesheets throw on cssRules access; the <link> path
			// above already covers them when href is present.
		}
	}
};

export const useDocumentPip = () => {
	const [pipWindow, setPipWindow] = useState<Window | null>(null);
	// True after a parent reload while a PiP was open. Chrome blocks
	// requestWindow without a user gesture, so we surface a one-click prompt
	// instead of failing silently.
	const [reopenPending, setReopenPending] = useState<boolean>(
		() => sessionStorage.getItem(REOPEN_FLAG) === "true",
	);
	const pipWindowRef = useRef<Window | null>(null);

	const open = useCallback(async (options: DocumentPipOptions) => {
		const api = getPipApi();
		if (!api) return;
		if (pipWindowRef.current) return;
		const win = await api.requestWindow(options);
		cloneStylesIntoPip(win.document);
		// Note: Chrome's PiP titlebar shows the opener's origin (e.g.
		// "localhost:8484"), not the PiP document.title — there is no API to
		// override it as of Chrome 147.
		win.document.body.dataset.pip = "true";
		// Persist intent so a parent reload can offer to re-open the PiP.
		sessionStorage.setItem(REOPEN_FLAG, "true");
		setReopenPending(false);
		const onClose = () => {
			pipWindowRef.current = null;
			setPipWindow(null);
			sessionStorage.removeItem(REOPEN_FLAG);
			setReopenPending(false);
		};
		win.addEventListener("pagehide", onClose);
		pipWindowRef.current = win;
		setPipWindow(win);
	}, []);

	const close = useCallback(() => {
		const win = pipWindowRef.current;
		if (!win) return;
		sessionStorage.removeItem(REOPEN_FLAG);
		setReopenPending(false);
		win.close();
	}, []);

	const dismissReopen = useCallback(() => {
		sessionStorage.removeItem(REOPEN_FLAG);
		setReopenPending(false);
	}, []);

	useEffect(() => {
		// On parent reload, any previously-open PiP window remains alive but
		// disconnected from our React state — it still shows the stale DOM and
		// doesn't react to new code. Close it so the user starts fresh.
		const orphan = getPipApi()?.window;
		if (orphan && orphan !== pipWindowRef.current) {
			orphan.close();
		}
	}, []);

	const resize = useCallback((width: number, height: number) => {
		// resizeTo requires user activation in document-PiP. Swallow the
		// NotAllowedError so a missed gesture doesn't crash the React tree.
		try {
			pipWindowRef.current?.resizeTo(width, height);
		} catch {
			// no-op: window stays at its current size
		}
	}, []);

	return { pipWindow, open, close, resize, reopenPending, dismissReopen };
};
