import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthenticationResult } from '@azure/msal-browser';

import { MsalAuthService } from '@/services/MsalAuthService';
import { activeAccount, belongsToConfiguredTenant, FABRIC_SCOPES, getToken, msal } from '@/services/msal';
import { isFramed } from '@/services/authStartup';

const account = vi.hoisted(() => ({
  localAccountId: 'user-1', homeAccountId: 'home-1', username: 'demo@example.com', name: 'Demo User',
  tenantId: 'test-tenant', environment: 'login.microsoftonline.com',
}));
const result: AuthenticationResult = {
  account, authority: 'https://login.microsoftonline.com/test-tenant',
  uniqueId: 'user-1', tenantId: 'test-tenant', scopes: ['https://api.fabric.microsoft.com/.default'],
  idToken: 'test-id-token', idTokenClaims: {}, accessToken: 'test-access-token',
  fromCache: false, expiresOn: new Date('2030-01-01T00:00:00Z'),
  tokenType: 'Bearer', correlationId: 'test-correlation',
};
vi.mock('@/services/msal', () => ({
  activeAccount: vi.fn(),
  belongsToConfiguredTenant: vi.fn(),
  ensureMsalReady: vi.fn().mockResolvedValue(undefined),
  FABRIC_SCOPES: ['https://api.fabric.microsoft.com/.default'],
  FOUNDRY_SCOPES: ['https://ai.azure.com/.default'],
  getToken: vi.fn(),
  msal: { loginPopup: vi.fn(), setActiveAccount: vi.fn(), logoutPopup: vi.fn(), ssoSilent: vi.fn() },
}));
vi.mock('@/services/authStartup', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/authStartup')>();
  return { ...actual, isFramed: vi.fn().mockReturnValue(false) };
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(activeAccount).mockReturnValue(account);
  vi.mocked(belongsToConfiguredTenant).mockReturnValue(true);
  vi.mocked(msal.loginPopup).mockResolvedValue(result);
  vi.mocked(getToken).mockResolvedValue('test-fabric-token');
  vi.mocked(isFramed).mockReturnValue(false);
});

describe('MSAL sign-in scopes', () => {
  it('requests one resource .default without merging Foundry into extraScopesToConsent', async () => {
    const user = await new MsalAuthService().signIn();
    expect(msal.loginPopup).toHaveBeenCalledExactlyOnceWith({ scopes: FABRIC_SCOPES, prompt: 'select_account' });
    expect(msal.setActiveAccount).toHaveBeenCalledWith(account);
    expect(user).toEqual({ id: 'user-1', email: 'demo@example.com', name: 'Demo User' });
  });

  it('propagates sign-in errors without reporting a successful session', async () => {
    vi.mocked(msal.loginPopup).mockRejectedValueOnce(new Error('Sign-in rejected'));
    await expect(new MsalAuthService().signIn()).rejects.toThrow('Sign-in rejected');
    expect(msal.setActiveAccount).not.toHaveBeenCalled();
  });

  it('rejects a sign-in whose active account cannot be resolved', async () => {
    vi.mocked(activeAccount).mockReturnValue(null);
    await expect(new MsalAuthService().signIn()).rejects.toThrow('Sign-in returned no account');
  });

  it('rejects a different tenant instead of installing its account', async () => {
    vi.mocked(belongsToConfiguredTenant).mockReturnValue(false);
    await expect(new MsalAuthService().signIn()).rejects.toThrow('configured demo tenant');
    expect(msal.setActiveAccount).not.toHaveBeenCalled();
  });
});

describe('MSAL session recovery', () => {
  it('does not accept cached identity after Entra rejected silent authentication', async () => {
    const service = new MsalAuthService();
    vi.mocked(getToken).mockRejectedValueOnce(new Error('AADSTS50197: please sign-in again'));
    expect(await service.initEmbeddedAuth()).toBeNull();
    expect(await service.getCurrentUser()).toBeNull();
    expect(msal.loginPopup).not.toHaveBeenCalled();
    expect(msal.logoutPopup).not.toHaveBeenCalled();
    expect(msal.setActiveAccount).not.toHaveBeenCalled();

    const user = await service.signIn();
    expect(msal.loginPopup).toHaveBeenCalledWith({ scopes: FABRIC_SCOPES, prompt: 'login' });
    expect(await service.getCurrentUser()).toEqual(user);
  });

  it('keeps valid cached sessions silent', async () => {
    const service = new MsalAuthService();
    expect(await service.initEmbeddedAuth()).toEqual({ id: 'user-1', email: 'demo@example.com', name: 'Demo User' });
    expect(getToken).toHaveBeenCalledExactlyOnceWith(FABRIC_SCOPES, false);
    expect(await service.getCurrentUser()).not.toBeNull();
    expect(msal.loginPopup).not.toHaveBeenCalled();
  });

  it('does not recover a cached identity after a failed silent SSO attempt', async () => {
    const service = new MsalAuthService();
    vi.mocked(activeAccount).mockReturnValueOnce(null);
    vi.mocked(msal.ssoSilent).mockRejectedValueOnce(new Error('login_required'));
    expect(await service.initEmbeddedAuth()).toBeNull();
    expect(await service.getCurrentUser()).toBeNull();
  });

  it('does not start an interactive or nested silent sign-in from an embedded app', async () => {
    vi.mocked(activeAccount).mockReturnValue(null);
    vi.mocked(isFramed).mockReturnValue(true);
    const service = new MsalAuthService();
    expect(await service.initEmbeddedAuth()).toBeNull();
    expect(await service.getCurrentUser()).toBeNull();
    expect(msal.ssoSilent).not.toHaveBeenCalled();
    expect(msal.loginPopup).not.toHaveBeenCalled();
  });

  it('requires verification again after sign-out', async () => {
    const service = new MsalAuthService();
    await service.signIn();
    await service.signOut();
    expect(await service.getCurrentUser()).toBeNull();
  });
});
