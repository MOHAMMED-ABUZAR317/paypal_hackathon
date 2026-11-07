import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("RainCheck UI crashed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page">
          <div className="callout callout--danger" role="alert">
            <span className="callout__mark">!</span>
            <div>
              <strong>The interface hit an unexpected error.</strong>
              <p>{this.state.error.message}</p>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => window.location.reload()}
              >
                Reload the app
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
