import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode | ((error: Error, reset: () => void) => ReactNode);
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: any) {
    console.error('React ErrorBoundary caught:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        if (typeof this.props.fallback === 'function') {
          return this.props.fallback(this.state.error || new Error('Unknown error'), this.handleReset);
        }
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen bg-gray-950 flex items-center justify-center p-8">
          <div className="bg-gray-900 border border-red-800 rounded-lg p-8 max-w-lg text-center shadow-xl">
            <h2 className="text-2xl font-bold text-red-400 mb-4">Something went wrong</h2>
            <p className="text-gray-400 mb-6 text-sm">
              {this.state.error?.message || 'An unexpected error occurred in this view.'}
            </p>
            <div className="flex gap-4 justify-center">
              <button
                onClick={this.handleReset}
                className="bg-gray-800 hover:bg-gray-700 px-5 py-2 rounded text-white font-medium border border-gray-700 transition-colors"
              >
                Try Again
              </button>
              <button
                onClick={() => {
                  this.handleReset();
                  window.location.href = '/app/';
                }}
                className="bg-blue-600 hover:bg-blue-700 px-5 py-2 rounded text-white font-medium transition-colors"
              >
                Return to Dashboard
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
