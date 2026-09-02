import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter({
      pages: process.env.BUILD_DIR || 'build',
      assets: process.env.BUILD_DIR || 'build',
      fallback: 'index.html'
    }),
    paths: {
      base: process.env.BASE_PATH ?? '/querybloom'
    },
    version: {
      name: '1.0.0'
    }
  }
};

export default config;
