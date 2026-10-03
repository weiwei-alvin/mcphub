// Test-environment shim: server-everything's streamableHttp transport calls
// app.listen(PORT) with no host (all interfaces). Force loopback for that call.
import http from "node:http";
const listen = http.Server.prototype.listen;
http.Server.prototype.listen = function (port, ...rest) {
  if ((typeof port === "number" || typeof port === "string") && typeof rest[0] !== "string") {
    return listen.call(this, port, "127.0.0.1", ...rest);
  }
  return listen.call(this, port, ...rest);
};
await import("./node_modules/@modelcontextprotocol/server-everything/dist/transports/streamableHttp.js");
