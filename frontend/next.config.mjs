/** Static export: `npm run build` writes plain files to `out/`, so the UI needs no Node server
 *  and keeps working when the backend is asleep (see docs/STAGE_05.md). */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};
export default nextConfig;
