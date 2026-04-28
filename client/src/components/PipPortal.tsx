import { type ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";

interface PipPortalProps {
	pipWindow: Window | null;
	children: ReactNode;
}

export function PipPortal({ pipWindow, children }: PipPortalProps) {
	const [mountNode, setMountNode] = useState<HTMLElement | null>(null);

	useEffect(() => {
		if (!pipWindow) {
			setMountNode(null);
			return;
		}
		const root = pipWindow.document.createElement("div");
		root.className = "pip-root";
		pipWindow.document.body.appendChild(root);
		setMountNode(root);
		return () => {
			root.remove();
		};
	}, [pipWindow]);

	if (!mountNode) return null;
	return createPortal(children, mountNode);
}
