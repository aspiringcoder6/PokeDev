import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const nativeClient = new URL(
  "../../../../agent-harness-server/deepseek-harness/plugins/vai-adlc-verify-ui/client/client.js",
  import.meta.url,
);
const memoryClient = new URL(
  "../../../../agent-harness-server/deepseek-harness/plugins/vai-adlc-project-memory/client/client.js",
  import.meta.url,
);
export default defineConfig({
  root: fileURLToPath(new URL("../..", import.meta.url)),
  // Do not load the application's production .env in this fixture preview.
  envDir: fileURLToPath(new URL(".", import.meta.url)),
  cacheDir: fileURLToPath(
    new URL("../../node_modules/.vite-verification-preview", import.meta.url),
  ),
  resolve: {
    alias: { "@": fileURLToPath(new URL("../../src", import.meta.url)) },
  },
  server: { host: "127.0.0.1", port: 4178, strictPort: true },
  plugins: [
    {
      name: "offline-verification-preview",
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          if (request.url === "/harness-verification-client.js") {
            response.setHeader("content-type", "text/javascript");
            response.end(await readFile(nativeClient, "utf8"));
            return;
          }
          if (request.url === "/harness-memory-client.js") {
            response.setHeader("content-type", "text/javascript");
            response.end(await readFile(memoryClient, "utf8"));
            return;
          }
          if (
            /^(?:\/offline-h6[abcd])?\/contracts\/harness\/source-session\//.test(
              request.url ?? "",
            )
          ) {
            const slice = request.url.startsWith("/offline-h6d/")
              ? "h6d"
              : request.url.startsWith("/offline-h6c/")
                ? "h6c"
                : request.url.startsWith("/offline-h6b/")
                  ? "h6b"
                  : "h6a";
            const html = (
              await readFile(new URL("index.html", import.meta.url), "utf8")
            ).replace(
              '<div id="root">',
              `<div id="root" data-preview-embedded="true" data-preview-slice="${slice}" data-preview-theme="light">`,
            );
            response.setHeader("content-type", "text/html");
            response.end(await server.transformIndexHtml(request.url, html));
            return;
          }
          next();
        });
      },
    },
  ],
});
