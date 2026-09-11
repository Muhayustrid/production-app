import path from "node:path";

import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";
import { defineConfig } from "vite";

// Mirrors pos_next/POS/vite.config.js: the frappe-ui vite plugin builds the
// hashed assets into the app's public dir and copies the built index.html into
// www/, which Frappe serves as a standard www page (route /production-app).
export default defineConfig({
	plugins: [
		frappeui({
			frappeProxy: true,
			jinjaBootData: true,
			lucideIcons: true,
			buildConfig: {
				indexHtmlPath: "../production_app/www/production-app.html",
				outDir: "../production_app/public/production",
				emptyOutDir: true,
				// No sourcemaps in the committed build output (Phase 3
				// carry-forward); must be set HERE - the plugin's config hook
				// overrides the top-level build config, where the default is true.
				sourcemap: false,
			},
		}),
		vue(),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
});
