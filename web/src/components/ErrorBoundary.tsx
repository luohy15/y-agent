import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  // Shown in the fallback message, e.g. "Notes panel". Falls back to a generic message.
  label?: string;
  className?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

// Top-level and per-panel crash containment: a throw in `children` renders an
// inline fallback here instead of unmounting the whole React tree (the failure
// mode that white-screened the app before this existed).
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`ErrorBoundary caught an error${this.props.label ? ` in ${this.props.label}` : ""}`, error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className={`flex flex-col items-center justify-center gap-2 p-4 text-center ${this.props.className ?? "h-full"}`}>
          <p className="text-sm text-sol-red">
            {this.props.label ? `${this.props.label} crashed.` : "Something went wrong."}
          </p>
          <p className="text-xs text-sol-base01 max-w-md break-words">{this.state.error.message}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-3 py-1 rounded bg-sol-blue/80 text-sol-base03 text-xs hover:bg-sol-blue cursor-pointer"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
