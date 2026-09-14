import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const backendHost = process.env.BACKEND_HOST || 'localhost';
const backendPort = process.env.BACKEND_PORT || '8000';
const publicHost = process.env.FRONTEND_PUBLIC_HOST;
const endpointsResolved = path.resolve(__dirname, 'src/lib/abstat/endpoints.json');

export default defineConfig({
  plugins: [sveltekit()],
  resolve: {
    alias: {
      '$endpoints': endpointsResolved,
    }
  },
  server: {
    host: true,
    allowedHosts: publicHost ? [publicHost] : [],
    hmr: publicHost ? {
      host: publicHost,
      protocol: 'wss',
      clientPort: 443,
    } : undefined,
    proxy: {
      '/api': {
        target: `http://${backendHost}:${backendPort}`,
        changeOrigin: true,
      },
      '/querybloom/api': {
        target: `http://${backendHost}:${backendPort}`,
        changeOrigin: true,
      }
    }
  }
});

