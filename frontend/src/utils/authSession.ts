export const AUTH_SESSION_EXPIRED_EVENT = 'bt-nms:auth-session-expired';

export const notifyAuthSessionExpired = (): void => {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') {
    return;
  }

  window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
};
