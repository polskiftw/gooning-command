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

export default {
  async fetch(request, env, ctx) {
    const response = await viewer.fetch(request, env, ctx);
    const headers = new Headers(response.headers);

    headers.set("x-robots-tag", ROBOTS_POLICY);
    headers.set("permissions-policy", PERMISSIONS_POLICY);
    headers.set("x-content-type-options", "nosniff");
    headers.set("referrer-policy", "no-referrer");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
