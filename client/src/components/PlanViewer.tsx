import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchPlan, type PlanFileResponse } from "../api";

interface PlanViewerProps {
	sessionId: string;
	planPath: string | null;
	planExists: boolean;
}

const basename = (path: string) => path.split("/").pop() || path;

export function PlanViewer({
	sessionId,
	planPath,
	planExists,
}: PlanViewerProps) {
	const [isModalOpen, setIsModalOpen] = useState(false);

	// Reserve a hint slot even when no plan exists, so per-card hint letters
	// stay stable across cards. The placeholder is visually hidden but keeps
	// the same data-hint-target attributes — pressing the hint shows a tooltip
	// explaining there's no plan rather than navigating.
	if (!planPath) {
		return (
			<button
				type="button"
				className="plan-placeholder"
				data-hint-target=""
				data-hint-scope="card"
				data-hint-card-id={sessionId}
				data-hint-label="No plan file for this session"
				aria-hidden="true"
				tabIndex={-1}
			/>
		);
	}

	const fileName = basename(planPath);

	return (
		<div className="plan-section">
			<button
				type="button"
				className="plan-header"
				data-hint-target=""
				data-hint-scope="card"
				data-hint-card-id={sessionId}
				onClick={() => setIsModalOpen(true)}
				title={planPath}
			>
				<span className="plan-label">plan:</span>
				<span className="plan-filename">{fileName}</span>
				{!planExists && <span className="plan-missing">(missing)</span>}
			</button>
			{isModalOpen && (
				<PlanModal
					sessionId={sessionId}
					planPath={planPath}
					onClose={() => setIsModalOpen(false)}
				/>
			)}
		</div>
	);
}

interface PlanModalProps {
	sessionId: string;
	planPath: string;
	onClose: () => void;
}

function PlanModal({ sessionId, planPath, onClose }: PlanModalProps) {
	const [plan, setPlan] = useState<PlanFileResponse | null>(null);
	const [isLoading, setIsLoading] = useState(true);
	const [loadError, setLoadError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		setIsLoading(true);
		setLoadError(null);
		setPlan(null);
		fetchPlan(sessionId)
			.then((result) => {
				if (!cancelled) setPlan(result);
			})
			.catch((err: Error) => {
				if (!cancelled) setLoadError(err.message);
			})
			.finally(() => {
				if (!cancelled) setIsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [sessionId]);

	useEffect(() => {
		const onKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", onKeyDown);
		return () => window.removeEventListener("keydown", onKeyDown);
	}, [onClose]);

	const onBackdropClick = (e: React.MouseEvent) => {
		if (e.target === e.currentTarget) onClose();
	};

	return (
		<div
			className="plan-modal-backdrop"
			onClick={onBackdropClick}
			role="presentation"
		>
			<div className="plan-modal" role="dialog" aria-label="Plan file viewer">
				<div className="plan-modal-header">
					<div className="plan-modal-title" title={planPath}>
						{basename(planPath)}
					</div>
					<button
						type="button"
						className="plan-modal-close"
						onClick={onClose}
						aria-label="Close plan viewer"
					>
						×
					</button>
				</div>
				<div className="plan-modal-body">
					{isLoading && <div className="plan-loading">Loading...</div>}
					{loadError && <div className="plan-error">{loadError}</div>}
					{plan?.exists && (
						<div className="plan-markdown">
							<ReactMarkdown remarkPlugins={[remarkGfm]}>
								{plan.content}
							</ReactMarkdown>
						</div>
					)}
					{plan && !plan.exists && (
						<div className="plan-missing-body">
							Plan file no longer exists on disk.
						</div>
					)}
				</div>
			</div>
		</div>
	);
}
