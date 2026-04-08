interface ToastProps {
	message: string | null;
}

export function Toast({ message }: ToastProps) {
	return <div className={`open-toast${message ? " show" : ""}`}>{message}</div>;
}
