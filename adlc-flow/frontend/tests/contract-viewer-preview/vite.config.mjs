import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const root = fileURLToPath(new URL("../..", import.meta.url));
const nativeClient = new URL(
  "../../../../agent-harness-server/deepseek-harness/plugins/vai-adlc-contract-ui/client/client.js",
  import.meta.url,
);
export default defineConfig({
  root,
  envDir: fileURLToPath(new URL(".", import.meta.url)),
  cacheDir: fileURLToPath(
    new URL("../../node_modules/.vite-contract-preview", import.meta.url),
  ),
  resolve: {
    alias: { "@": fileURLToPath(new URL("../../src", import.meta.url)) },
  },
  server: { host: "127.0.0.1", port: 4177, strictPort: true },
  plugins: [
    {
      name: "fixture-only-contract-preview",
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          if (request.url === "/harness-contract-client.js") {
            response.setHeader("content-type", "text/javascript");
            response.end(await readFile(nativeClient, "utf8"));
            return;
          }
          if (
            /^\/contracts\/harness\/[A-Za-z0-9._-]+\/$/.test(request.url ?? "")
          ) {
            request.url =
              "/tests/contract-viewer-preview/index.html?embedded=true" +
              (request.url.includes("/session-h5d/") ? "&recovery=true" : "");
          }
          next();
        });
      },
    },
  ],
});
