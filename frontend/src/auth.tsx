import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as api from "./api";
import type { Role, User } from "./types";

// The session token lives in memory and in sessionStorage (per tab, cleared when the tab closes).
// It is never written to localStorage, cookies set by script, or URLs.
const TOKEN_KEY = "obscura.session";
let memoryToken: string | null = null;

export function getToken(): string | null {
  return memoryToken;
}

function storeToken(token: string | null): void {
  memoryToken = token;
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): memory only */
  }
}

function loadToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export const ROLE_RANK: Record<Role, number> = { viewer: 0, redactor: 1, supervisor: 2, admin: 3 };

export function hasRole(user: Pick<User, "role"> | null | undefined, min: Role): boolean {
  if (!user) return false;
  return (ROLE_RANK[user.role] ?? -1) >= ROLE_RANK[min];
}

export function canSeeOriginals(user: Pick<User, "role"> | null | undefined): boolean {
  return hasRole(user, "redactor");
}

type AuthStatus = "loading" | "anonymous" | "authenticated";

/** When sign-in is off and this browser runs on the same computer, fetch a session for the built-in account. */
async function tryLocal(): Promise<User | null> {
  try {
    const mode = await api.authMode();
    if (!mode.local_access) return null;
    const res = await api.localLogin();
    storeToken(res.token);
    return res.user;
  } catch {
    return null;
  }
}

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  /** true when the app was opened without signing in (built-in local account). */
  localMode: boolean;
  notice: string | null;
  clearNotice: () => void;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<User>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [notice, setNotice] = useState<string | null>(null);
  const userRef = useRef<User | null>(null);
  userRef.current = user;
  const renewing = useRef(false);

  useEffect(() => {
    const signInLocally = async () => {
      const u = await tryLocal();
      if (u) {
        setUser(u);
        setStatus("authenticated");
      } else setStatus("anonymous");
      return u;
    };
    api.configureApi({
      getToken,
      onUnauthorized: () => {
        const wasLocal = !!userRef.current?.local;
        const hadSession = !!memoryToken;
        storeToken(null);
        if (wasLocal) {
          // the local session simply expired: get a new one without bothering the user
          if (!renewing.current) {
            renewing.current = true;
            void signInLocally().finally(() => {
              renewing.current = false;
            });
          }
          return;
        }
        setUser(null);
        setStatus("anonymous");
        if (hadSession) setNotice("Your session has ended. Please sign in again.");
      },
    });
    const saved = loadToken();
    if (!saved) {
      void signInLocally();
      return;
    }
    memoryToken = saved;
    api
      .me()
      .then((u) => {
        setUser(u);
        setStatus("authenticated");
      })
      .catch(() => {
        storeToken(null);
        void signInLocally();
      });
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    storeToken(res.token);
    setUser(res.user);
    setStatus("authenticated");
    setNotice(null);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      if (memoryToken) await api.logout();
    } catch {
      /* the session may already be gone */
    }
    storeToken(null);
    setUser(null);
    setStatus("anonymous");
  }, []);

  const changePassword = useCallback(async (current: string, next: string) => {
    const res = await api.changePassword(current, next);
    storeToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const refresh = useCallback(async () => {
    const u = await api.me();
    setUser(u);
  }, []);

  const localMode = !!user?.local;
  const value = useMemo<AuthContextValue>(
    () => ({ user, status, localMode, notice, clearNotice: () => setNotice(null), login, logout, changePassword, refresh }),
    [user, status, localMode, notice, login, logout, changePassword, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** The signed-in user (only use below the authenticated routes). */
export function useUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("no user");
  return user;
}
