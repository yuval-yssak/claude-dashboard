interface ModelBadgeProps {
	model: string | null;
	thinkingRecent: boolean;
}

const MODEL_LABELS: ReadonlyArray<readonly [RegExp, string]> = [
	[/^claude-opus-4-7/, "Opus 4.7"],
	[/^claude-opus-4-6/, "Opus 4.6"],
	[/^claude-opus-4/, "Opus 4"],
	[/^claude-sonnet-4-6/, "Sonnet 4.6"],
	[/^claude-sonnet-4/, "Sonnet 4"],
	[/^claude-haiku-4-5/, "Haiku 4.5"],
	[/^claude-haiku-4/, "Haiku 4"],
];

function prettyModel(model: string): string {
	const match = MODEL_LABELS.find(([pattern]) => pattern.test(model));
	return match ? match[1] : model;
}

export function ModelBadge({ model, thinkingRecent }: ModelBadgeProps) {
	if (!model) return null;
	const label = prettyModel(model);
	const title = thinkingRecent
		? `${model} · most recent response used extended thinking`
		: model;
	return (
		<span className="model-badge" title={title}>
			{label}
			{thinkingRecent && <span className="model-thinking-indicator"> ✻</span>}
		</span>
	);
}
