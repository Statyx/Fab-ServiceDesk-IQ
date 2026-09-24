import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import userEvent from '@testing-library/user-event';

import { AuthProvider, useAuth } from '@/hooks/AuthContext';
import { AuthPage } from '@/components/AuthPage';
import type { IAuthService } from '@/services/IAuthService';

const stubAuthService: IAuthService = {
  fabricAuthEnabled: false,
  async signIn() {
    return { id: 'u1', email: 'dev@contoso.com', name: 'dev' };
  },
  async signOut() {},
  async getCurrentUser() {
    return null;
  },
  async initEmbeddedAuth() {
    return null;
  },
};

describe('AuthProvider', () => {
  it('renders children once initial auth check completes', async () => {
    render(
      <AuthProvider authService={stubAuthService}>
        <div data-testid="content">ready</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('content')).toHaveTextContent('ready');
    });
  });
  it('retains a rejected sign-in message when the loading guard remounts the sign-in page', async () => {
    const service: IAuthService = {
      ...stubAuthService,
      signIn: async () => { throw new Error('Consent request rejected'); },
    };
    function SignInGuard() {
      const { loading } = useAuth();
      return loading ? <p>Signing in…</p> : <AuthPage />;
    }
    render(<AuthProvider authService={service}><SignInGuard /></AuthProvider>);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in with Microsoft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Consent request rejected');
    expect(screen.getByRole('button', { name: 'Sign in with Microsoft' })).toBeEnabled();
  });
});
