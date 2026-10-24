import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/space-grotesk/latin-500.css";
import "@fontsource/space-grotesk/latin-600.css";
import "./ui/tokens.css";
import "./ui/base.css";
import "./ui/shell.css";
import "./styles.css";
import { applyTheme, storedTheme } from "./ui/theme";

applyTheme(storedTheme(null)); // before the first paint: no flash of the other theme

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
