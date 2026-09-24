import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  initialize: vi.fn(),
  handleRedirectPromise: vi.fn(),
  getAllAccounts: vi.fn(),
  getActiveAccount: vi.fn(),
  setActiveAccount: vi.fn(),
  acquireTokenSilent: vi.fn(),
  acquireTokenPopup: vi.fn(),
}));

vi.mock('@azure/msal-browser', () => ({
  PublicClientApplication: class {
    initialize = client.initialize;
    handleRedirectPromise = client.handleRedirectPromise;
    getAllAccounts = client.getAllAccounts;
    getActiveAccount = client.getActiveAccount;
    setActiveAccount = client.setActiveAccount;
    acquireTokenSilent = client.acquireTokenSilent;
    acquireTokenPopup = client.acquireTokenPopup;
  },
  InteractionRequiredAuthError: class extends Error {},
}));

const target = { tenantId: 'demo-tenant', username: 'demo@example.com' };
const corporate = { tenantId: 'corporate-tenant', username: 'work@example.com' };

beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  vi.stubEnv('VITE_ENTRA_CLIENT_ID', 'demo-client');
  vi.stubEnv('VITE_ENTRA_TENANT_ID', 'demo-tenant');
  client.initialize.mockResolvedValue(undefined);
  client.handleRedirectPromise.mockResolvedValue(null);
  client.getAllAccounts.mockReturnValue([]);
  client.getActiveAccount.mockReturnValue(null);
});

afterEach(() => vi.unstubAllEnvs());

describe('tenant-bound browser sessions', () => {
  it('selects the configured tenant rather than the first cached corporate account', async () => {
    client.getActiveAccount.mockReturnValue(corporate);
    client.getAllAccounts.mockReturnValue([corporate, target]);
    const auth = await import('@/services/msal');
    await auth.ensureMsalReady();
    expect(auth.activeAccount()).toEqual(target);
    expect(client.setActiveAccount).toHaveBeenCalledWith(target);
  });

  it('does not treat a corporate-only browser cache as a demo session', async () => {
    client.getActiveAccount.mockReturnValue(corporate);
    client.getAllAccounts.mockReturnValue([corporate]);
    const auth = await import('@/services/msal');
    await auth.ensureMsalReady();
    expect(auth.activeAccount()).toBeNull();
    expect(client.setActiveAccount).toHaveBeenCalledWith(null);
    await expect(auth.getToken(auth.FABRIC_SCOPES, false)).rejects.toThrow('No signed-in account');
    expect(client.acquireTokenPopup).not.toHaveBeenCalled();
  });

  it('requests account selection instead of silently reusing browser SSO', async () => {
    client.acquireTokenPopup.mockResolvedValue({ account: target, accessToken: 'test-token' });
    const auth = await import('@/services/msal');
    expect(await auth.getToken(auth.FABRIC_SCOPES)).toBe('test-token');
    expect(client.acquireTokenPopup).toHaveBeenCalledWith({
      scopes: auth.FABRIC_SCOPES, prompt: 'select_account',
    });
  });

  it('rejects tokens returned for a different tenant', async () => {
    client.acquireTokenPopup.mockResolvedValue({ account: corporate, accessToken: 'wrong-token' });
    const auth = await import('@/services/msal');
    await expect(auth.getToken(auth.FABRIC_SCOPES)).rejects.toThrow('configured demo tenant');
    expect(client.setActiveAccount).not.toHaveBeenCalledWith(corporate);
  });

  it('keeps a valid target-tenant session silent', async () => {
    client.getActiveAccount.mockReturnValue(target);
    client.acquireTokenSilent.mockResolvedValue({ account: target, accessToken: 'test-token' });
    const auth = await import('@/services/msal');
    expect(await auth.getToken(auth.FABRIC_SCOPES)).toBe('test-token');
    expect(client.acquireTokenSilent).toHaveBeenCalledWith({ scopes: auth.FABRIC_SCOPES, account: target });
    expect(client.acquireTokenPopup).not.toHaveBeenCalled();
  });
});
