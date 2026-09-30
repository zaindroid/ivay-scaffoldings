import typescript from "@rollup/plugin-typescript";
import terser from "@rollup/plugin-terser";

export default {
  input: "src/index.ts",
  output: { file: "dist/ivay.js", format: "iife", name: "Ivay", sourcemap: false },
  plugins: [
    typescript({ tsconfig: "./tsconfig.json", noEmit: false, declaration: false, outDir: "dist", include: ["src/**/*.ts"] }),
    terser({ compress: { passes: 2 }, mangle: true }),
  ],
};
