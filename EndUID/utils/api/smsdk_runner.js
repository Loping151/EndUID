/* eslint-disable no-console */
const fs = require('fs');
const http = require('http');
const https = require('https');
const vm = require('vm');

const sdkPath = process.argv[2];

if (!sdkPath || !fs.existsSync(sdkPath)) {
  console.error('smsdk runner: missing sm.sdk.js');
  process.exit(1);
}

process.on('uncaughtException', (err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});

process.on('unhandledRejection', (err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});

const store = {};

const localStorage = {
  getItem(key) {
    return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null;
  },
  setItem(key, value) {
    store[key] = String(value);
  },
  removeItem(key) {
    delete store[key];
  },
};

function parseAcceptLanguage(raw) {
  if (!raw || typeof raw !== 'string') {
    return ['zh-CN', 'zh'];
  }
  return raw
    .split(',')
    .map((part) => part.split(';')[0].trim())
    .filter(Boolean);
}

function isMobileUserAgent(ua) {
  return /Android|iPhone|iPad|iPod/i.test(ua);
}

function derivePlatform(ua) {
  if (/Android/i.test(ua)) return 'Linux armv8l';
  if (/iPhone|iPad|iPod/i.test(ua)) return 'iPhone';
  if (/Windows/i.test(ua)) return 'Win32';
  if (/Mac OS X/i.test(ua)) return 'MacIntel';
  return 'Linux x86_64';
}

function deriveScreen(ua) {
  if (isMobileUserAgent(ua)) {
    return {
      width: 1080,
      height: 2400,
      availWidth: 1080,
      availHeight: 2340,
      devicePixelRatio: 3,
      innerWidth: 360,
      innerHeight: 780,
      outerWidth: 360,
      outerHeight: 780,
    };
  }
  return {
    width: 1920,
    height: 1080,
    availWidth: 1920,
    availHeight: 1040,
    devicePixelRatio: 1,
    innerWidth: 1920,
    innerHeight: 1040,
    outerWidth: 1920,
    outerHeight: 1080,
  };
}

function normalizeUrl(raw) {
  try {
    return new URL(raw);
  } catch {
    return new URL('https://www.skland.com/');
  }
}

const envUserAgent = process.env.SMSDK_USER_AGENT;
const envAcceptLanguage = process.env.SMSDK_ACCEPT_LANGUAGE;
const envReferer = process.env.SMSDK_REFERER;
const envPlatform = process.env.SMSDK_PLATFORM;

const userAgent = envUserAgent || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36';
const languageList = parseAcceptLanguage(envAcceptLanguage);
const language = languageList[0] || 'zh-CN';
const platform = envPlatform || derivePlatform(userAgent);
const refererUrl = normalizeUrl(envReferer || 'https://www.skland.com/');
const screenProfile = deriveScreen(userAgent);

const document = {
  location: {
    href: refererUrl.href,
    protocol: refererUrl.protocol,
    host: refererUrl.host,
    hostname: refererUrl.hostname,
    pathname: refererUrl.pathname,
    search: refererUrl.search,
  },
  referrer: refererUrl.href,
  URL: refererUrl.href,
  body: { appendChild() {} },
  documentElement: { clientWidth: screenProfile.innerWidth, clientHeight: screenProfile.innerHeight },
  readyState: 'complete',
  addEventListener() {},
  attachEvent() {},
  createElement(tag) {
    if (tag === 'canvas') {
      return {
        width: 0,
        height: 0,
        getContext() {
          return {
            textBaseline: 'top',
            font: '14px Arial',
            fillStyle: '#000',
            globalCompositeOperation: 'source-over',
            fillRect() {},
            fillText() {},
            measureText(text) {
              return { width: text ? text.length * 7 : 0 };
            },
          };
        },
        toDataURL() {
          return 'data:image/png;base64,' + Buffer.from('canvas').toString('base64');
        },
      };
    }
    return {
      style: {},
      setAttribute() {},
      appendChild() {},
      getContext() { return null; },
    };
  },
};

Object.defineProperty(document, 'cookie', {
  get() {
    return store.__cookie || '';
  },
  set(value) {
    store.__cookie = String(value);
  },
});

const navigator = {
  userAgent,
  platform,
  language,
  languages: languageList,
  hardwareConcurrency: isMobileUserAgent(userAgent) ? 8 : 16,
  maxTouchPoints: isMobileUserAgent(userAgent) ? 5 : 0,
  plugins: [],
  mimeTypes: [],
};

const screen = {
  width: screenProfile.width,
  height: screenProfile.height,
  availWidth: screenProfile.availWidth,
  availHeight: screenProfile.availHeight,
  colorDepth: 24,
  pixelDepth: 24,
};

const context = {
  window: null,
  self: null,
  addEventListener: () => {},
  attachEvent: () => {},
  document,
  navigator,
  screen,
  devicePixelRatio: screenProfile.devicePixelRatio,
  innerWidth: screenProfile.innerWidth,
  innerHeight: screenProfile.innerHeight,
  outerWidth: screenProfile.outerWidth,
  outerHeight: screenProfile.outerHeight,
  location: {
    href: refererUrl.href,
    protocol: refererUrl.protocol,
    host: refererUrl.host,
    hostname: refererUrl.hostname,
    pathname: refererUrl.pathname,
    search: refererUrl.search,
  },
  localStorage,
  sessionStorage: localStorage,
  atob: (str) => Buffer.from(str, 'base64').toString('binary'),
  btoa: (str) => Buffer.from(str, 'binary').toString('base64'),
  setTimeout,
  clearTimeout,
  console,
};

context.window = context;
context.self = context;

class XMLHttpRequest {
  constructor() {
    this.readyState = 0;
    this.status = 0;
    this.response = null;
    this.responseText = '';
    this.responseType = '';
    this.statusText = '';
    this.onreadystatechange = null;
    this.onload = null;
    this.onerror = null;
    this.withCredentials = false;
    this._headers = {};
    this._method = 'GET';
    this._url = '';
  }

  open(method, url) {
    this._method = method;
    this._url = url;
    this.readyState = 1;
  }

  setRequestHeader(key, value) {
    this._headers[key] = value;
  }

  send(body) {
    try {
      const u = new URL(this._url);
      const lib = u.protocol === 'https:' ? https : http;
      const options = {
        method: this._method,
        hostname: u.hostname,
        port: u.port || (u.protocol === 'https:' ? 443 : 80),
        path: u.pathname + u.search,
        headers: this._headers,
      };
      const req = lib.request(options, (res) => {
        const chunks = [];
        res.on('data', (d) => chunks.push(d));
        res.on('end', () => {
          this.status = res.statusCode || 0;
          this.responseText = Buffer.concat(chunks).toString('utf-8');
          if (this.responseType === 'json') {
            try {
              this.response = JSON.parse(this.responseText);
            } catch {
              this.response = null;
            }
          } else {
            this.response = this.responseText;
          }
          this.readyState = 4;
          if (this.onreadystatechange) this.onreadystatechange();
          if (this.onload) this.onload();
        });
      });
      req.on('error', (err) => {
        this.status = 0;
        this.statusText = err.message || 'error';
        this.readyState = 4;
        if (this.onreadystatechange) this.onreadystatechange();
        if (this.onerror) this.onerror(err);
      });
      if (body) req.write(body);
      req.end();
    } catch (err) {
      this.status = 0;
      this.statusText = err.message || 'error';
      this.readyState = 4;
      if (this.onreadystatechange) this.onreadystatechange();
      if (this.onerror) this.onerror(err);
    }
  }
}

context.XMLHttpRequest = XMLHttpRequest;

context._smConf = {
  organization: 'UWXspnCCJN4sfYlNfqps',
  appId: 'default',
  publicKey: 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCmxMNr7n8ZeT0tE1R9j/mPixoinPkeM+k4VGIn/s0k7N5rJAfnZ0eMER+QhwFvshzo0LNmeUkpR8uIlU/GEVr8mN28sKmwd2gpygqj0ePnBmOW4v0ZVwbSYK+izkhVFk2V/doLoMbWy6b+UnA8mkjvg0iYWRByfRsK2gdl7llqCwIDAQAB',
  protocol: 'https',
  apiHost: 'fp-it.portal101.cn',
  apiPath: '/deviceprofile/v4',
};
context._smReadyFuncs = [];

const code = fs.readFileSync(sdkPath, 'utf-8');
try {
  vm.runInNewContext(code, context);
} catch (err) {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
}

const start = Date.now();
const timeoutMs = Number(process.env.SMSDK_TIMEOUT || 15000);

function poll() {
  try {
    const did = context.SMSdk && context.SMSdk.getDeviceId ? context.SMSdk.getDeviceId() : '';
    if (did) {
      console.log(did);
      process.exit(0);
    }
  } catch {
    // ignore
  }
  if (Date.now() - start > timeoutMs) {
    console.error('smsdk runner: timeout');
    process.exit(2);
  }
  setTimeout(poll, 200);
}

poll();
