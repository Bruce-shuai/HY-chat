"use client";

import React from "react";

type FallbackArgs = {
  error: Error;
  reset: () => void;
};

type LocalErrorBoundaryProps = {
  children: React.ReactNode;
  fallback: (args: FallbackArgs) => React.ReactNode;
  label: string;
  resetKey?: string | null;
};

type LocalErrorBoundaryState = {
  error: Error | null;
};

export class LocalErrorBoundary extends React.Component<
  LocalErrorBoundaryProps,
  LocalErrorBoundaryState
> {
  state: LocalErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): LocalErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`${this.props.label}异常`, error, info);
  }

  componentDidUpdate(prevProps: LocalErrorBoundaryProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return this.props.fallback({
        error: this.state.error,
        reset: this.reset,
      });
    }

    return this.props.children;
  }
}
