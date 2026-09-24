import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { basePath } from '@/domain/nav';

/**
 * Navigate to a console section, staying inside whatever mount the app is served from.
 *
 * The screens are mounted twice — once guarded at the root, once under `/preview` for
 * design work — so a bare `navigate('/incident')` from a preview screen leaves the preview
 * and lands on the guarded route, which bounces to sign-in. Every cross-screen jump goes
 * through here so that cannot happen, and so the rule lives in one place rather than in
 * each button that happens to link somewhere.
 */
export function useGo() {
  const navigate = useNavigate();
  const base = basePath(useLocation().pathname);
  return useCallback((to: string) => navigate(`${base}${to}`), [navigate, base]);
}
