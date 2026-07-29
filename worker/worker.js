import viewer from "./viewer.js";

const ROBOTS_POLICY = "noindex, nofollow, noarchive, nosnippet, noimageindex";
const PERMISSIONS_POLICY = [
  "accelerometer=()",
  "camera=()",
  "geolocation=()",
  "gyroscope=()",
  "microphone=()",
  "payment=()",
  "usb=()",
].join(", ");
const CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "media-src 'self' blob:",
  "connect-src 'self'",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
  "manifest-src 'none'",
].join("; ");

export default {
  async fetch(request, env, ctx) {
    const response = await viewer.fetch(request, env, ctx);
    const headers = new Headers(response.headers);

    headers.set("x-robots-tag", ROBOTS_POLICY);
    headers.set("permissions-policy", PERMISSIONS_POLICY);
    headers.set("content-security-policy", CONTENT_SECURITY_POLICY);
    headers.set("x-content-type-options", "nosniff");
    headers.set("referrer-policy", "no-referrer");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
