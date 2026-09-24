import { isFramed, withTimeout } from './authStartup';
import type { AuthUser, IAuthService } from './IAuthService';
import {
  activeAccount,
  belongsToConfiguredTenant,
  ensureMsalReady,
  FABRIC_SCOPES,
  getToken,
  msal,
} from './msal';

import type { AccountInfo } from '@azure/msal-browser';

function toUser(a: AccountInfo): AuthUser {
  const email = a.username ?? '';
  return {
    id: a.localAccountId ?? a.homeAccountId ?? email,
    email,
    name: a.name || email.split('@')[0],
  };
}

/**
 * IAuthService backed by Entra directly, instead of the Rayfin brokered session.
 *
 * The template ships MockAuthService (localhost) and RayfinAuthService (Fabric brokered).
 * Neither can produce a token for the Fabric API or the Eventhouse, and reading those is this
 * console's entire purpose — so sign-in and data access are unified on one identity here rather
 * than running two parallel auth stacks whose sessions could disagree about who the user is.
 */
export class MsalAuthService implements IAuthService {
  readonly fabricAuthEnabled = true;
  private sessionVerified = false;
  private needsFreshSignIn = false;

  async signIn(): Promise<AuthUser> {
    this.sessionVerified = false;
    await ensureMsalReady();
    // Each service (Power BI, Kusto, Fabric) requests its own resource token separately:
    // merging several .default scopes into the authorize request exceeds Entra's static-scope
    // limit (AADSTS70011).
    const r = await msal.loginPopup({
      scopes: FABRIC_SCOPES,
      // Choose the demo identity even when Edge already has a corporate SSO session.
      // An explicitly rejected session still needs full reauthentication (50197).
      prompt: this.needsFreshSignIn ? 'login' : 'select_account',
    });
    if (r.account && !belongsToConfiguredTenant(r.account)) {
      throw new Error('The selected account is not in the configured demo tenant. Choose the demo account.');
    }
    if (r.account) msal.setActiveAccount(r.account);
    const a = activeAccount();
    if (!a) throw new Error('Sign-in returned no account.');
    this.sessionVerified = true;
    this.needsFreshSignIn = false;
    return toUser(a);
  }

  async signOut(): Promise<void> {
    await ensureMsalReady();
    const account = activeAccount() ?? undefined;
    await msal.logoutPopup({ account });
    this.sessionVerified = false;
  }

  async getCurrentUser(): Promise<AuthUser | null> {
    await ensureMsalReady();
    // AuthProvider falls back to this after silent startup. A cached identity is
    // not a verified session if that startup request failed.
    if (!this.sessionVerified) return null;
    const a = activeAccount();
    return a ? toUser(a) : null;
  }

  /**
   * Startup path: recover a session without any UI.
   *
   * Runs inside and outside the Fabric iframe. Returning `null` here is a normal outcome, not an
   * error — it just means the user has to click Sign in.
   *
   * Every await is bounded. This method is the only thing standing between the app and an
   * unbounded spinner, and it runs against a host we cannot reproduce locally.
   */
  async initEmbeddedAuth(): Promise<AuthUser | null> {
    this.sessionVerified = false;
    await withTimeout(ensureMsalReady(), 'msal.initialize + handleRedirectPromise');

    if (activeAccount()) {
      try {
        await withTimeout(getToken(FABRIC_SCOPES, false), 'acquireTokenSilent');
        this.sessionVerified = true;
        return await this.getCurrentUser();
      } catch {
        this.needsFreshSignIn = true;
        return null;
      }
    }

    // ssoSilent authenticates through a hidden iframe pointed at Entra. Nested inside the
    // portal's own iframe that request is third-party — partitioned storage, and in a private
    // window no session cookie at all — so it cannot succeed here, and an attempt that cannot
    // succeed is only a chance to stall. Fall straight through to the Sign in button.
    if (isFramed()) return null;

    try {
      const r = await withTimeout(msal.ssoSilent({ scopes: FABRIC_SCOPES }), 'ssoSilent');
      if (!belongsToConfiguredTenant(r.account)) return null;
      if (r.account) msal.setActiveAccount(r.account);
      this.sessionVerified = true;
      return await this.getCurrentUser();
    } catch {
      this.needsFreshSignIn = true;
      return null;
    }
  }
}
