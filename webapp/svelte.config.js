import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter({
      fallback: 'index.html'
    }),
    paths: {
      base: process.env.BASE_PATH || ''
    },
    version: {
      name: '1.0.0'
    }
  }
};

export default config;
