type StorageData = Record<string, string>;

const createStorage = () => {
  let data: StorageData = {};
  return {
    clear: () => {
      data = {};
    },
    getItem: (key: string) => (Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null),
    key: (index: number) => Object.keys(data)[index] ?? null,
    removeItem: (key: string) => {
      delete data[key];
    },
    setItem: (key: string, value: string) => {
      data[key] = String(value);
    },
    get length() {
      return Object.keys(data).length;
    },
  } as Storage;
};

let currentUrl = new URL('http://localhost:5173/');
const updateLocation = (target: string) => {
  currentUrl = new URL(target, currentUrl.href);
};

const locationLike = {
  get href() {
    return currentUrl.href;
  },
  get protocol() {
    return currentUrl.protocol;
  },
  get hostname() {
    return currentUrl.hostname;
  },
  get host() {
    return currentUrl.host;
  },
  get port() {
    return currentUrl.port;
  },
  assign: updateLocation,
  replace: updateLocation,
  toString: () => currentUrl.href,
};

const windowLike = {
  location: locationLike,
  localStorage: createStorage(),
  sessionStorage: createStorage(),
  history: {
    pushState: (_state: unknown, _title: string, url?: string | URL | null) => {
      if (url) {
        updateLocation(String(url));
      }
    },
    replaceState: (_state: unknown, _title: string, url?: string | URL | null) => {
      if (url) {
        updateLocation(String(url));
      }
    },
  },
};

Object.defineProperty(globalThis, 'window', {
  configurable: true,
  value: windowLike,
});
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: windowLike.localStorage,
});
Object.defineProperty(globalThis, 'sessionStorage', {
  configurable: true,
  value: windowLike.sessionStorage,
});
