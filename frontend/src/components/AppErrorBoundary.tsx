import { Component, type ErrorInfo, type ReactNode } from 'react';

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('MReader UI render failure', error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="min-h-screen bg-ink-950 text-ink-100 flex items-center justify-center p-6">
        <section className="w-full max-w-lg rounded-2xl border border-red-900/60 bg-ink-900 p-6">
          <h1 className="font-display text-xl font-semibold">This view could not render</h1>
          <p className="mt-2 text-sm text-ink-400">The application is still running. Reload this view or return to a safe page.</p>
          <p className="mt-3 break-words rounded-lg bg-ink-950 p-3 text-xs text-red-300">{this.state.error.message || 'Unexpected UI error'}</p>
          <div className="mt-5 flex flex-wrap gap-2">
            <button className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium" onClick={() => window.location.reload()}>Reload view</button>
            <button className="rounded-lg bg-ink-800 px-4 py-2 text-sm" onClick={() => window.history.back()}>Back</button>
            <a className="rounded-lg bg-ink-800 px-4 py-2 text-sm" href="/">Home</a>
          </div>
        </section>
      </main>
    );
  }
}
